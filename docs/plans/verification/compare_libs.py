"""Scratch: stdlib indicator primitives vs TA-Lib / pandas / polars on synthetic prices. Not part of the repo."""
import inspect
import random
import statistics
import subprocess
import sys
import time
from bisect import bisect_left
from statistics import fmean

import numpy as np
import pandas as pd
import polars as pl
import talib


# ---------- stdlib primitives (what libs/indicators.py would hold) ----------
def sma(values: list[float], n: int) -> float | None:
    return fmean(values[-n:]) if len(values) >= n else None


def ema_series(values: list[float], n: int) -> list[float]:
    """SMA-seeded EMA; out[i] belongs to values[n - 1 + i]."""
    alpha = 2 / (n + 1)
    out = [fmean(values[:n])]
    for value in values[n:]:
        out.append(out[-1] + alpha * (value - out[-1]))
    return out


def macd_hist(values: list[float], normalise: bool = True) -> list[float]:
    """Histogram series (PPO if normalise, else classic MACD); hist[i] belongs to values[33 + i]."""
    fast = ema_series(values, 12)[14:]
    slow = ema_series(values, 26)
    line = [(a - b) / b if normalise else a - b for a, b in zip(fast, slow)]
    signal = ema_series(line, 9)
    return [a - b for a, b in zip(line[8:], signal)]


def rsi(values: list[float], n: int = 14) -> float | None:
    if len(values) <= n:
        return None
    deltas = [b - a for a, b in zip(values, values[1:])]
    gain = fmean(max(d, 0) for d in deltas[:n])
    loss = fmean(max(-d, 0) for d in deltas[:n])
    for delta in deltas[n:]:
        gain = (gain * (n - 1) + max(delta, 0)) / n
        loss = (loss * (n - 1) + max(-delta, 0)) / n
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def percentile_rank(sorted_values: list[float], x: float) -> float:
    return bisect_left(sorted_values, x) / (len(sorted_values) - 1)


# ---------- data ----------
def walk(seed: int, rows: int) -> list[float]:
    rng = random.Random(seed)
    price, out = 50.0, []
    for _ in range(rows):
        price *= 1 + rng.gauss(0.0003, 0.02)
        out.append(price)
    return out


def loc(*functions) -> int:
    return sum(1 for fn in functions for line in inspect.getsource(fn).splitlines() if line.strip() and not line.strip().startswith(('"""', '#')))


# ---------- 1. correctness vs TA-Lib and pandas ----------
close = walk(1, 300)
arr = np.array(close)
print("1. CORRECTNESS on one 300-row series")
print("   SMA20  stdlib vs pandas rolling      max diff:", abs(sma(close, 20) - pd.Series(close).rolling(20).mean().iloc[-1]))
e12 = ema_series(close, 12)[-1]
print("   EMA12  stdlib vs TA-Lib EMA          diff:", abs(e12 - talib.EMA(arr, 12)[-1]))
print("   EMA12  stdlib vs pandas ewm(adjust=False) diff:", abs(e12 - pd.Series(close).ewm(span=12, adjust=False).mean().iloc[-1]))
print("   RSI14  stdlib vs TA-Lib RSI          diff:", abs(rsi(close) - talib.RSI(arr, 14)[-1]))
delta = pd.Series(close).diff()
up, dn = delta.clip(lower=0), -delta.clip(upper=0)
pd_rsi = 100 - 100 / (1 + up.ewm(alpha=1 / 14, adjust=False).mean() / dn.ewm(alpha=1 / 14, adjust=False).mean())
print("   RSI14  stdlib vs pandas ewm(alpha=1/14)   diff:", abs(rsi(close) - pd_rsi.iloc[-1]), "(pandas seeds with the first value, not an SMA)")
_, _, talib_hist = talib.MACD(arr, 12, 26, 9)
mine = macd_hist(close, normalise=False)
print("   MACD hist (absolute) stdlib vs TA-Lib, diff at row 40/60/100/200/299:")
for row in (40, 60, 100, 200, 299):
    print(f"      row {row}: {abs(mine[row - 33] - talib_hist[row]):.2e}  (|hist|={abs(talib_hist[row]):.3f})")

# ---------- 2. warm-up: how much does the answer depend on how many rows we give it? ----------
print("\n2. WARM-UP: last-row value on the last L rows vs on 1500 rows (200 random series)")
series = [walk(seed, 1500) for seed in range(200)]
true_hist = [macd_hist(s)[-1] for s in series]
true_rsi = [rsi(s) for s in series]
print("   L    PPO hist err (% of price, median/95th)   RSI err (points, median/95th)")
for length in (40, 61, 100, 150, 260):
    herr = sorted(abs(macd_hist(s[-length:])[-1] - t) * 100 for s, t in zip(series, true_hist))
    rerr = sorted(abs(rsi(s[-length:]) - t) for s, t in zip(series, true_rsi))
    print(f"   {length:<4} {herr[100]:.4f} / {herr[190]:.4f}                       {rerr[100]:.3f} / {rerr[190]:.3f}")
typical = statistics.median(abs(h) * 100 for h in true_hist)
print(f"   (typical |PPO hist| = {typical:.3f}% of price)")
for length in (20, 30, 45, 70):
    rerr = sorted(abs(rsi(s[-length:]) - t) for s, t in zip(series, true_rsi))
    print(f"   RSI with only {length} rows: err median/95th = {rerr[100]:.2f} / {rerr[190]:.2f} points")

# ---------- 3. speed: 150 symbols x 260 rows ----------
symbols = [walk(seed, 260) for seed in range(150)]


def stdlib_run() -> None:
    for s in symbols:
        sma(s, 20), sma(s, 50), sma(s, 200)
        macd_hist(s)
        rsi(s)
        statistics.pstdev([b / a - 1 for a, b in zip(s[-21:], s[-20:])])


def pandas_run() -> None:
    for s in symbols:
        c = pd.Series(s)
        c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
        f, sl = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
        ppo = (f - sl) / sl
        ppo - ppo.ewm(span=9, adjust=False).mean()
        d = c.diff()
        d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean() / (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        c.pct_change().rolling(20).std()


frame = pl.DataFrame({"symbol": [i for i in range(150) for _ in range(260)], "close": [v for s in symbols for v in s]})


def polars_run() -> None:
    frame.with_columns(
        pl.col("close").rolling_mean(20).over("symbol").alias("sma20"),
        pl.col("close").rolling_mean(50).over("symbol").alias("sma50"),
        pl.col("close").rolling_mean(200).over("symbol").alias("sma200"),
        pl.col("close").ewm_mean(span=12, adjust=False).over("symbol").alias("e12"),
        pl.col("close").ewm_mean(span=26, adjust=False).over("symbol").alias("e26"),
        pl.col("close").pct_change().rolling_std(20).over("symbol").alias("vol"),
    )


def best(fn, repeat: int = 5) -> float:
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return min(times) * 1000


print("\n3. SPEED, 150 symbols x 260 rows (SMA20/50/200, MACD hist, RSI14, vol20; polars covers the vectorisable half)")
print(f"   stdlib {best(stdlib_run):7.1f} ms   pandas {best(pandas_run):7.1f} ms   polars {best(polars_run):7.1f} ms")
print(f"   stdlib primitives: {loc(sma, ema_series, macd_hist, rsi, percentile_rank)} lines of code")

# ---------- 4. import cost ----------
print("\n4. IMPORT TIME (fresh interpreter)")
for module in ("statistics", "numpy", "pandas", "polars", "talib"):
    start = time.perf_counter()
    subprocess.run([sys.executable, "-I", "-c", f"import {module}"], check=True)
    print(f"   import {module:<11} {(time.perf_counter() - start) * 1000:6.0f} ms (incl. interpreter start)")
