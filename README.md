# vnv-stock-analysis

Fetch the latest daily price of Vietnamese stocks from free public endpoints (no API key).

## What's implemented

| Path | What |
|---|---|
| `libs/prices/` | `DNSE`, `VPS`, `VNDirect` classes. Each has `get_latest_price(symbol) -> Price`. `Price` is a pydantic model (symbol, source, date, open, high, low, close, volume; thousand VND). |
| `libs/logger/` | `Logger` interface (`debug/info/warning/error`) and `LogxideLogger`, its adapter over [logxide](https://github.com/Indosaram/logxide). Logs go to stderr. |
| `scripts/vn_stock_latest_price_retrieval.py` | Fetches the latest price of every symbol in `data/hose_symbols.csv` (DNSE → VPS → VNDirect, 1 retry per source, 2 s between symbols) and writes one JSON array. A symbol that fails everywhere is skipped; exit 4 if none was fetched. |
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

### Commands

| Command | What it does |
|---|---|
| `uv run pytest` | Unit tests (no network) with coverage on `libs/`. Fails if coverage is under 95%. |
| `uv run pytest -m live --no-cov` | Live smoke tests against the real endpoints. Not run by default. |
| `uv run ruff check libs tests` | Lint. Add `--fix` to auto-fix. |
| `lefthook run pre-commit` | Run the pre-commit checks by hand. |
| `uv run python -m scripts.vn_stock_latest_price_retrieval [symbols_csv] [output_json]` | Fetch the latest price of all symbols (default `data/hose_symbols.csv`, takes about 20 min) and write `out/vn_stock_latest_prices.json`. |

The pre-commit hook (`lefthook.yml`) runs the lint, then the unit tests with the coverage gate. A commit is blocked if either fails.

Settings for pytest, coverage and ruff live in `pyproject.toml`.

### CI

`.github/workflows/ci.yml` runs on every pull request to `master`. The jobs run in order, and each one needs the previous one to pass.

| Job | Runs |
|---|---|
| `install` | `uv sync --locked`, and saves the uv cache (keyed on `uv.lock`) |
| `lint` | `ruff check libs tests` |
| `test` | `pytest` with the 95% coverage gate |
| `audit` | `pip-audit` on the locked runtime dependencies |

Later jobs restore the cache from `install`, so their own `uv sync --locked` only has to link the packages. Commit `uv.lock` whenever you change dependencies, or `--locked` makes CI fail.

### Code rules

- Always add type hints: every function parameter and return type, and class fields (use pydantic models for data that crosses a function boundary). It makes the code easier to read and understand. Ruff's `ANN` rules enforce this, so the lint (and the pre-commit hook) fails on a missing hint.

### Layout

```
libs/prices/   base.py (Price, PriceSource, PriceNotFoundError, helpers), dnse.py, vps.py, vndirect.py
tests/libs/prices/   test_base.py, test_dnse.py, test_vps.py, test_vndirect.py, test_live.py
libs/logger/   base.py (Logger), logxide.py (LogxideLogger)
tests/libs/logger/   test_logxide.py
scripts/   vn_holiday.py, vn_stock_latest_price_retrieval.py
tests/scripts/   test_vn_holiday.py, test_vn_stock_latest_price_retrieval.py
```

Every source raises `PriceNotFoundError` for an invalid or unknown ticker; other failures (network, HTTP 5xx) propagate as they are. `Price` rejects non-positive prices, a negative volume, and open/close outside low/high.

To add a source, subclass `PriceSource` in `libs/prices/`, export it in `__init__.py`, and add a matching `tests/libs/prices/test_<name>.py`.
