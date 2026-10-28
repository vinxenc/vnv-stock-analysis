# Verification record

What was checked behind the numbers in [phase-1-sql-screens.md](../phase-1-sql-screens.md) ("Libraries" and the min-rows column), and the results. The scripts that produced them were scratch code and were **removed**; this file is the specification to re-implement them.

All results are from 2026-10-28 on **synthetic random-walk prices** (daily returns ~ N(0.0003, 0.02), start price 50), not HOSE data. Re-run them against real history once it exists in `prices`. They ran in a throwaway environment outside the project (`uv run --no-project --python 3.12 --with numpy --with ta-lib ...`), so nothing was added to the repo.

| Check | Packages | What it did | Result |
|---|---|---|---|
| PyPI facts | none (read-only network) | Read versions, release dates, dependencies and wheel sizes from `https://pypi.org/pypi/<name>/json` for numpy, pandas, polars, ta, pandas-ta, TA-Lib | Numbers in the Libraries comparison table |
| Full-series equality | numpy, ta-lib | stdlib SMA(20), EMA(12), EMA(26), RSI(14) (SMA-seeded EMA; Wilder RSI seeded with the mean of the first 14 changes) against TA-Lib on every row of 50 series of 300 rows | Maximum difference about 1e-13 |
| PPO recipe | numpy, ta-lib | `ppo = talib.PPO(close, 12, 26, matype=1) / 100`, `histogram = ppo - talib.EMA(ppo, 9)` on the non-NaN part, against the plan's PPO histogram; first non-NaN index of `talib.MACD` | Maximum difference 7e-18; `talib.MACD` is absolute and seeds differently, equal only after about 150–200 rows |
| Candle gaps | numpy, ta-lib | 15-bar downtrend followed by one hand-built pattern per case, with and without a gap; `CDLMORNINGSTAR`, `CDLPIERCING`, `CDLENGULFING`, `CDLHAMMER` | Morning star and piercing line fire only with a gap; engulfing and hammer fire |
| Warm-up in points | none (stdlib) | For each EMA / Wilder indicator (#8–#11, #22): value on the last L rows against the value on 1500 rows (300 series), error converted to score points through the indicator's ramp, 99th percentile | Smallest L with error ≤ 0.5 point: #8 45, #9 70, #10 55, #11 70, #22 60 rows |
| Library comparison | numpy, pandas, polars, ta-lib | Correctness against pandas and TA-Lib on one series, speed and import time on 150 symbols × 260 rows | stdlib 21 ms, pandas 78 ms, polars 1.7 ms (vectorisable half only) |
