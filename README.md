# vnv-stock-analysis

Fetch the latest daily price of Vietnamese stocks from free public endpoints (no API key).

## What's implemented

| Path | What |
|---|---|
| `libs/prices/` | `DNSE`, `VPS`, `VNDirect` classes. Each has `get_latest_price(symbol) -> Price`. `Price` is a pydantic model (symbol, source, date, open, high, low, close, volume; thousand VND). |
| `libs/logger/` | `Logger` interface (`debug/info/warning/error`), `LogxideLogger` (adapter over [logxide](https://github.com/Indosaram/logxide), logs to stderr) and `GithubActionsLogger` (writes GitHub Actions annotations to stdout). |
| `scripts/vn_stock_latest_price_retrieval.py` | Fetches the latest price of every symbol in `data/hose_symbols.csv` (DNSE → VPS → VNDirect, 1 retry per source, 1 s between symbols) and writes one JSON array. A symbol that fails everywhere is skipped; exit 4 if none was fetched. |
| `libs/db/` | `models.py`: `Price`, the `prices` table (primary key `symbol` + `date`), also the model the price sources return (`libs.prices.Price` reuses it). Create it with `Price.model_validate(data)`: SQLModel skips validation in `Price(**data)`. |
| `scripts/vn_stock_daily_price_store.py` | Reads the JSON above and upserts it into the `prices` table (`ON CONFLICT (symbol, date) DO UPDATE`, one transaction). Needs `$DATABASE_URL`. Exit 4 if the file holds no price. A repeated (symbol, date) in the file: the last row wins. 10 s connect and 60 s statement timeouts. |
| `scripts/vn_stock_screen.py` | Reads `prices` and writes `out/liquid_symbols.csv` (a `code` column): the symbols that traded today (Vietnam time) and whose average turnover (`close × volume`) over their last 20 sessions is at least 20 billion VND (a symbol with fewer rows is averaged over the rows it has). Needs `$DATABASE_URL`. Crashes (exit 1) when the newest session in `prices` is not today, so a late or failed sync is never reported as fresh data; exit 4 if nobody is liquid enough. |
| `migrations/` | Alembic migrations (`alembic.ini` at the root); the database comes from `$DATABASE_URL`. |
| `docker-compose.yml` | Local Postgres 17 (user, password and database all `vnv`). |
| `.github/workflows/migrate.yml` | `Migrate-Database`: runs `alembic upgrade head` on a push to `master` that changes `migrations/`. Needs the `DATABASE_URL` secret of the `production` environment. |
| `data/hose_symbols.csv` | The 406 stocks listed on HOSE (as of 2026-10-23). |
| `tests/` | Unit tests, same layout as `libs/`, plus opt-in live tests. |
| `scripts/vn_holiday.py` | Says whether today (Vietnam time) is a weekend or VN public holiday. Exit 0 = day off, 3 = working day, anything else = error. |
| `scripts/pipeline_state.py`, `scripts/notification.py`, `.github/actions/pipeline-state/` | Pipeline state files and the notification that reads them (see below). |
| `.github/workflows/vn-stock-prices-sync.yml` | `VN Stock Prices Sync`: weekday cron (20:00 Vietnam time). Jobs: `start-analyze` → `install` → `is_holiday` → `retrieve_prices` → `vn_stock_daily_price_store` (downloads the JSON artifact and runs the store script with the `production` environment's `DATABASE_URL` secret), then `notification`. See "Pipeline state and notification" below. |
| `.github/workflows/vn-stock-analysis.yml` | `VN Stock Analysis`: weekday cron (22:00 Vietnam time) plus manual run. It only reads `prices` (stored by `VN Stock Prices Sync` two hours earlier), never fetches. Jobs so far: `start-analyze` → `install` → `is_holiday` (a day off skips the later jobs) → `vn_stock_screen` (uploads the `vn-stock-screen` artifact, with the `production` environment's `DATABASE_URL` secret), then `notification`. The history and analyze jobs are planned in `docs/plans/phase-1-sql-screens.md`. |

The endpoints are undocumented and may change or block without notice.

## Develop locally

Needs [uv](https://docs.astral.sh/uv/) and [lefthook](https://lefthook.dev/) (`brew install uv lefthook`).

```bash
uv sync                  # create .venv and install deps (incl. dev tools)
lefthook install         # one-time: enable the pre-commit hook
```

### Database and migrations

```bash
docker compose up -d --wait                                            # local Postgres on :5432
export DATABASE_URL=postgresql+psycopg://vnv:vnv@localhost:5432/vnv    # alembic reads this
uv run alembic upgrade head                                            # create / update the tables
```

After changing `libs/db/models.py`, generate the migration and review it before committing:

```bash
uv run alembic revision --autogenerate -m "what changed"
uv run alembic upgrade head                                            # apply it to the local database
uv run alembic check                                                   # fails if models and migrations differ
```

`docker compose down -v` throws the local database away. Alembic is a dev dependency, so `uv sync` installs it.

In production the `Migrate-Database` workflow applies the migrations on every push to `master` that changes `migrations/` (a merged PR or a direct push). The job uses the `production` environment, so `DATABASE_URL` must be an environment secret there (Settings → Environments → production), e.g. `postgresql+psycopg://user:pass@host:5432/db`. A provider URL starting with `postgres://` also works (`libs.db.database_url` rewrites it); keep `?sslmode=require` if the host needs SSL and URL-encode special characters in the password.

### Commands

| Command | What it does |
|---|---|
| `uv run pytest` | Unit tests (no network, but **needs the local Postgres**, see below) with coverage on `libs/` and `scripts/`. Fails if coverage is under 95%. |
| `uv run pytest -m live --no-cov` | Live smoke tests against the real endpoints. Not run by default. |
| `uv run ruff check libs scripts tests` | Lint. Add `--fix` to auto-fix. |
| `lefthook run pre-commit` | Run the pre-commit checks by hand. |
| `uv run python -m scripts.vn_stock_daily_price_store [input_json]` | Upsert `out/vn_stock_latest_prices.json` into the database named by `$DATABASE_URL`. |
| `uv run python -m scripts.vn_stock_screen [output_csv]` | Write the liquid symbols (20-session average turnover) to `out/liquid_symbols.csv` (needs `$DATABASE_URL`). |
| `uv run python -m scripts.vn_stock_latest_price_retrieval [symbols_csv] [output_json]` | Fetch the latest price of all symbols (default `data/hose_symbols.csv`, takes about 20 min) and write `out/vn_stock_latest_prices.json`. |

### Pipeline state and notification

Every job of `VN Stock Prices Sync` and `VN Stock Analysis` before `notification` ends with the `.github/actions/pipeline-state` composite action. It runs even when the job failed, writes `state/<pipeline>.json` and uploads it as the artifact `pipeline-state-<pipeline>`:

```json
{"level": "info", "message": "Stored the prices in the database", "pipeline": "vn_stock_daily_price_store"}
```

| Job result | `level` | `message` |
|---|---|---|
| success | `info` (`is_holiday` on a day off: `warning`) | the job's success message |
| failed | `error` | the job's failure message |
| cancelled | `warning` | `<pipeline> was cancelled` |

`notification` (`if: always()`) downloads every `pipeline-state-*` artifact into `state/` and runs `python3 -m scripts.notification state` (system Python, no `uv sync`), which logs one annotation per file through `GithubActionsLogger`, titled with the pipeline: `info` → notice, `warning` → warning, `error` → error. A job that was skipped (everything after `is_holiday` on a day off, or after a failed job) writes no file, so it shows nothing. A job whose final result its file does not report is caught by the fallback: the workflow passes `toJSON(needs)` as `$NEEDS`, and a `failure` job is logged as an error unless its state is already `error`, a `cancelled` job as a warning unless its state is already `warning` or `error`. That covers a job that died before writing its file (failed checkout, lost runner) and one that failed or was cancelled after it (a post step such as the uv cache save). A file that cannot be read is logged as an error and the script exits 1. `pipeline_state.py` and `notification.py` use only the standard library (plus `GithubActionsLogger`, which does not import the third-party `logxide`: `libs.logger` loads `LogxideLogger` lazily), so both work even when `uv sync` is the step that failed. To add a pipeline job, end it with the action and name it; `notification` needs the job in its `needs`.

```bash
python3 scripts/pipeline_state.py state install success info "Dependencies installed" "install failed"   # write one
python3 -m scripts.notification state                                                                     # log them
```

### Testing locally

The database tests run against a real Postgres (the one in `docker-compose.yml`), not a fake:

```bash
docker compose up -d --wait   # start Postgres on 127.0.0.1:5432 (skip if it is already up)
uv run pytest                 # unit tests + coverage gate
```

- `tests/conftest.py` creates a separate `vnv_test` database on first use and drops and recreates the tables before every test, so your dev database `vnv` is never touched.
- No Postgres running: the DB tests fail with "Postgres is not reachable; run `docker compose up -d --wait`".
- Different server: set `TEST_DATABASE_SERVER` to a `postgresql+psycopg://user:pass@host:port/postgres` URL (a role that can `CREATE DATABASE`).
- The same applies to the pre-commit hook, which runs `pytest`: start Postgres first.
- To try the real script against your dev database: `export DATABASE_URL=postgresql+psycopg://vnv:vnv@localhost:5432/vnv`, `uv run alembic upgrade head`, then `uv run python -m scripts.vn_stock_daily_price_store`.

The pre-commit hook (`lefthook.yml`) runs the lint, then the unit tests with the coverage gate. A commit is blocked if either fails.

Settings for pytest, coverage and ruff live in `pyproject.toml`.

#### See the SQL

Set `SQL_LOG_ENABLE=1` to log every SQL statement with its parameters (through the project's logger, to stderr). It works for all three: `SQL_LOG_ENABLE=1 uv run alembic upgrade head`, `SQL_LOG_ENABLE=1 uv run python -m scripts.vn_stock_daily_price_store tests/data/prices_hpg_aam.json` and `SQL_LOG_ENABLE=1 uv run pytest -s` (`-s`, or `-rP` on a passing test, because pytest hides the output otherwise). SQLAlchemy's own `echo=True` is not used: logxide swallows it. In CI the `test` job sets it in the workflow (`env:` of the job, with `pytest -s`), so the log shows there without anything typed; locally `export SQL_LOG_ENABLE=1` once per shell instead of prefixing every command. Build every engine with `libs.db.connect()`, which wires the logging.

#### Seed the database

`tests/data/prices_hpg_aam.json` holds real history of two stocks (HPG, very liquid; AAM, almost untraded). CI migrates and seeds the job's Postgres service with it before `pytest`, and `test_screen_on_the_seeded_database` checks the screen against that data. The same locally (that test is skipped while `$DATABASE_URL` is unset):

```bash
export DATABASE_URL=postgresql+psycopg://vnv:vnv@localhost:5432/vnv
uv run alembic upgrade head
uv run python -m scripts.vn_stock_daily_price_store tests/data/prices_hpg_aam.json
uv run pytest
```

### CI

`.github/workflows/ci.yml` runs on every pull request to `master`. The jobs run in order, and each one needs the previous one to pass.

| Job | Runs |
|---|---|
| `install` | `uv sync --locked`, and saves the uv cache (keyed on `uv.lock`) |
| `lint` | `ruff check libs scripts tests` |
| `test` | Migrates and seeds the Postgres 17 service container (same credentials as `docker-compose.yml`) with `tests/data/prices_hpg_aam.json`, then `pytest` with the 95% coverage gate |
| `audit` | `pip-audit` on the locked runtime dependencies |

Later jobs restore the cache from `install`, so their own `uv sync --locked` only has to link the packages. Commit `uv.lock` whenever you change dependencies, or `--locked` makes CI fail.

**uv cache rule** (`ci.yml`, `vn-stock-prices-sync.yml` and `vn-stock-analysis.yml`): every `astral-sh/setup-uv` step sets `prune-cache: false`, and only the `install` job saves the cache. By default `setup-uv` runs `uv cache prune --ci` before saving, which deletes pre-built wheels; all our dependencies are wheels, so the saved cache was about 1 KB and every job downloaded the packages again. `prune-cache` is part of the cache key (`...-pruned-...` or not), so a job that restores must use the same value as `install`, or it looks up a different cache and misses. Every job except `install` also sets `save-cache: false`, restores the cache, and runs its own `uv sync --locked` to link the packages. The two pipeline workflows install with `--no-dev` (fewer wheels), so their `setup-uv` steps also set `cache-suffix: runtime`; otherwise they and `ci.yml` share one cache key. They share the `runtime` cache with each other, which is fine: both install the same set. A cache entry can't be overwritten, so if the runtime cache is saved first, `ci.yml` restores it without the dev wheels (pytest, ruff, pip-audit) and downloads them on every run. The reverse is harmless: a full cache saved first also contains the runtime wheels.

### Code rules

- Always add type hints: every function parameter and return type, and class fields (use pydantic models for data that crosses a function boundary). It makes the code easier to read and understand. Ruff's `ANN` rules enforce this, so the lint (and the pre-commit hook) fails on a missing hint.
- Give variables clear, descriptive names: no single-letter or cryptic names (`r`, `d`, `e`, `p`, `i`). Write `result`, `data`, `error`, `price`, `index` instead.
- No `print()` anywhere in `libs/` and `scripts/`. Log through the `Logger` interface (`libs/logger`): a library function takes a `Logger` or creates a `LogxideLogger(__name__)`, a script creates one at module level like `scripts/vn_stock_latest_price_retrieval.py`. `LogxideLogger` writes to stderr. To write GitHub Actions annotations use `GithubActionsLogger(title)` (it writes the `::notice::` / `::warning::` / `::error::` commands to stdout, where the runner reads them). Ruff's `T20` rule enforces this in `libs`, `scripts` and `migrations`; only `tests/` is exempt.
- Use UPPER_CASE only for constants (fixed values such as `NO_DATA`, `UA`, `SYMBOL_RE`). Anything else, like a logger, a client or a session, is lower case. Create it inside a function or as a lower-case variable, not as an upper-case global.
- File formats: CSV for a flat list of codes (`data/hose_symbols.csv`, `out/liquid_symbols.csv`; read with `read_symbols`), JSON for typed or nested records (prices, pipeline state, the analysis output; validate with the pydantic models). Do not mix the two for the same kind of data.

### Layout

```
libs/prices/   base.py (Price, PriceSource, PriceNotFoundError, helpers), dnse.py, vps.py, vndirect.py
tests/libs/prices/   test_base.py, test_dnse.py, test_vps.py, test_vndirect.py, test_live.py
libs/logger/   base.py (Logger), logxide.py (LogxideLogger, stderr), github_actions.py (GithubActionsLogger, workflow commands on stdout)
tests/libs/logger/   test_logxide.py, test_github_actions.py
scripts/   vn_holiday.py, vn_stock_latest_price_retrieval.py, vn_stock_daily_price_store.py, vn_stock_screen.py, pipeline_state.py, notification.py
tests/   conftest.py (Postgres fixtures: `pg_url`, `engine`), data/prices_hpg_aam.json (real DNSE history of HPG and AAM, 2026-09-15..2026-10-29, the seed)
tests/scripts/   test_vn_holiday.py, test_vn_stock_latest_price_retrieval.py, test_vn_stock_daily_price_store.py, test_vn_stock_screen.py, test_pipeline_state.py, test_notification.py
```

Every source raises `PriceNotFoundError` for an invalid or unknown ticker; other failures (network, HTTP 5xx) propagate as they are. `Price` rejects non-positive prices, and a negative volume.

**Adding a price source:** before it is used, compare it with the existing sources (DNSE, VPS, VNDirect) on the same symbols and sessions: `open`/`high`/`low`/`close` (adjusted, thousand VND) and `volume` (matched shares, put-through trades excluded) must be identical, because `prices` mixes whichever source answered and `scripts/vn_stock_screen.py` multiplies `close × volume`. Checked on 2026-10-29 for HPG, VCB and AAM over 8 sessions: the three sources were identical.

To add a source, subclass `PriceSource` in `libs/prices/`, export it in `__init__.py`, and add a matching `tests/libs/prices/test_<name>.py`.
