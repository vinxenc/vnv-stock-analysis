# vnv-stock-analysis

Fetch the latest daily price of Vietnamese stocks from free public endpoints (no API key).

## What's implemented

| Path | What |
|---|---|
| `libs/prices/` | `DNSE`, `VPS`, `VNDirect` classes. Each has `get_latest_price(symbol) -> Price`. `Price` is a pydantic model (symbol, source, date, open, high, low, close, volume; thousand VND). |
| `libs/logger/` | `Logger` interface (`debug/info/warning/error`) and `LogxideLogger`, its adapter over [logxide](https://github.com/Indosaram/logxide). Logs go to stderr. |
| `scripts/vn_stock_latest_price_retrieval.py` | Fetches the latest price of every symbol in `data/hose_symbols.csv` (DNSE → VPS → VNDirect, 1 retry per source, 1 s between symbols) and writes one JSON array. A symbol that fails everywhere is skipped; exit 4 if none was fetched. |
| `libs/db/` | `models.py`: `Price`, the `prices` table (primary key `symbol` + `date`), also the model the price sources return (`libs.prices.Price` reuses it). Create it with `Price.model_validate(data)`: SQLModel skips validation in `Price(**data)`. |
| `migrations/` | Alembic migrations (`alembic.ini` at the root); the database comes from `$DATABASE_URL`. |
| `docker-compose.yml` | Local Postgres 17 (user, password and database all `vnv`). |
| `.github/workflows/migrate.yml` | `Migrate-Database`: runs `alembic upgrade head` on a push to `master` that changes `migrations/`. Needs the `DATABASE_URL` secret of the `production` environment. |
| `data/hose_symbols.csv` | The 406 stocks listed on HOSE (as of 2026-10-23). |
| `tests/` | Unit tests, same layout as `libs/`, plus opt-in live tests. |
| `scripts/vn_holiday.py` | Says whether today (Vietnam time) is a weekend or VN public holiday. Exit 0 = day off, 3 = working day, anything else = error. |
| `.github/workflows/vn-stock-analysis.yml` | `VN-Stock-Analysis`: weekday cron (22:00 Vietnam time). Jobs: `start-analyze` (placeholder) → `is_holiday` → `notification` (level-coloured annotation: warning on a day off, error when no price was fetched) \| `retrieve_prices` → `vn_stock_daily_price_store` (downloads the JSON artifact and prints it for now). |

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
| `uv run pytest` | Unit tests (no network) with coverage on `libs/` and `scripts/`. Fails if coverage is under 95%. |
| `uv run pytest -m live --no-cov` | Live smoke tests against the real endpoints. Not run by default. |
| `uv run ruff check libs scripts tests` | Lint. Add `--fix` to auto-fix. |
| `lefthook run pre-commit` | Run the pre-commit checks by hand. |
| `uv run python -m scripts.vn_stock_latest_price_retrieval [symbols_csv] [output_json]` | Fetch the latest price of all symbols (default `data/hose_symbols.csv`, takes about 20 min) and write `out/vn_stock_latest_prices.json`. |

The pre-commit hook (`lefthook.yml`) runs the lint, then the unit tests with the coverage gate. A commit is blocked if either fails.

Settings for pytest, coverage and ruff live in `pyproject.toml`.

### CI

`.github/workflows/ci.yml` runs on every pull request to `master`. The jobs run in order, and each one needs the previous one to pass.

| Job | Runs |
|---|---|
| `install` | `uv sync --locked`, and saves the uv cache (keyed on `uv.lock`) |
| `lint` | `ruff check libs scripts tests` |
| `test` | `pytest` with the 95% coverage gate |
| `audit` | `pip-audit` on the locked runtime dependencies |

Later jobs restore the cache from `install`, so their own `uv sync --locked` only has to link the packages. Commit `uv.lock` whenever you change dependencies, or `--locked` makes CI fail.

**uv cache rule** (`ci.yml` and `vn-stock-analysis.yml`): every `astral-sh/setup-uv` step sets `prune-cache: false`, and only the `install` job saves the cache. By default `setup-uv` runs `uv cache prune --ci` before saving, which deletes pre-built wheels; all our dependencies are wheels, so the saved cache was about 1 KB and every job downloaded the packages again. `prune-cache` is part of the cache key (`...-pruned-...` or not), so a job that restores must use the same value as `install`, or it looks up a different cache and misses. Every job except `install` also sets `save-cache: false`, restores the cache, and runs its own `uv sync --locked` to link the packages. `vn-stock-analysis.yml` installs with `--no-dev` (fewer wheels), so its `setup-uv` steps also set `cache-suffix: runtime`; otherwise it and `ci.yml` share one cache key. A cache entry can't be overwritten, so if the runtime cache is saved first, `ci.yml` restores it without the dev wheels (pytest, ruff, pip-audit) and downloads them on every run. The reverse is harmless: a full cache saved first also contains the runtime wheels.

### Code rules

- Always add type hints: every function parameter and return type, and class fields (use pydantic models for data that crosses a function boundary). It makes the code easier to read and understand. Ruff's `ANN` rules enforce this, so the lint (and the pre-commit hook) fails on a missing hint.
- Give variables clear, descriptive names: no single-letter or cryptic names (`r`, `d`, `e`, `p`, `i`). Write `result`, `data`, `error`, `price`, `index` instead.
- Use UPPER_CASE only for constants (fixed values such as `NO_DATA`, `UA`, `SYMBOL_RE`). Anything else, like a logger, a client or a session, is lower case. Create it inside a function or as a lower-case variable, not as an upper-case global.

### Layout

```
libs/prices/   base.py (Price, PriceSource, PriceNotFoundError, helpers), dnse.py, vps.py, vndirect.py
tests/libs/prices/   test_base.py, test_dnse.py, test_vps.py, test_vndirect.py, test_live.py
libs/logger/   base.py (Logger), logxide.py (LogxideLogger)
tests/libs/logger/   test_logxide.py
scripts/   vn_holiday.py, vn_stock_latest_price_retrieval.py
tests/scripts/   test_vn_holiday.py, test_vn_stock_latest_price_retrieval.py
```

Every source raises `PriceNotFoundError` for an invalid or unknown ticker; other failures (network, HTTP 5xx) propagate as they are. `Price` rejects non-positive prices, and a negative volume.

To add a source, subclass `PriceSource` in `libs/prices/`, export it in `__init__.py`, and add a matching `tests/libs/prices/test_<name>.py`.
