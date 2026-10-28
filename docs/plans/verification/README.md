# Verification scripts

Scratch-quality scripts behind the numbers in [phase-1-sql-screens.md](../phase-1-sql-screens.md) ("Libraries" and the min-rows column). They are not production code: `ruff` checks only `libs scripts tests` and `pytest` collects only `tests/`, so these are neither linted nor tested.

All results below are from 2026-10-28 on **synthetic random-walk prices**, not HOSE data. Re-run them against real history once it exists in `prices`.

Run each one from this folder, outside the project environment, so nothing is added to the repo:

```bash
uv run --no-project --python 3.12 --with numpy --with ta-lib python -I full_series_check.py
```

| Script | Packages (`--with`) | What it checks | Result |
|---|---|---|---|
| `pypi_facts.py` | none (read-only network) | Versions, release dates, dependencies and wheel sizes on PyPI for numpy, pandas, polars, ta, pandas-ta, TA-Lib | Numbers in the Libraries comparison table |
| `full_series_check.py` | `numpy ta-lib` | stdlib SMA / EMA / RSI against TA-Lib on every row of 50 series | Maximum difference about 1e-13 |
| `ppo_check.py` | `numpy ta-lib` | `talib.PPO(matype=1)` plus `talib.EMA` reproduces the plan's PPO histogram; `talib.MACD` start index | Maximum difference 7e-18 |
| `candles_check.py` | `numpy ta-lib` | TA-Lib candle recognition with and without gaps, one hand-built example per case | Morning star and piercing line fire only with a gap |
| `warmup_points.py` | none (stdlib only; run with `uv run --no-project --python 3.12 python -I warmup_points.py`) | Warm-up error of the EMA / Wilder indicators converted to score points; gives the min-rows column | #8 45, #9 70, #10 55, #11 70, #22 60 rows |
| `compare_libs.py` | `numpy pandas polars ta-lib` | Correctness against pandas and TA-Lib on one series, last-row warm-up error, speed and import time of stdlib / pandas / polars | stdlib 21 ms, pandas 78 ms, polars 1.7 ms (vectorisable half) for 150 symbols × 260 rows |
