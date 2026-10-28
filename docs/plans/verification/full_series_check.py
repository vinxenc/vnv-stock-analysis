"""Scratch: stdlib SMA / EMA / RSI vs TA-Lib over the WHOLE series (every row), 50 random walks of 300 rows."""
import random
from statistics import fmean

import numpy as np
import talib


def sma_series(values, n):
    return [fmean(values[i - n + 1:i + 1]) for i in range(n - 1, len(values))]  # out[i] belongs to values[n - 1 + i]


def ema_series(values, n):
    alpha = 2 / (n + 1)
    out = [fmean(values[:n])]
    for value in values[n:]:
        out.append(out[-1] + alpha * (value - out[-1]))
    return out  # out[i] belongs to values[n - 1 + i]


def rsi_series(values, n=14):
    deltas = [b - a for a, b in zip(values, values[1:])]
    gain = fmean(max(d, 0) for d in deltas[:n])
    loss = fmean(max(-d, 0) for d in deltas[:n])
    out = [100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)]
    for delta in deltas[n:]:
        gain = (gain * (n - 1) + max(delta, 0)) / n
        loss = (loss * (n - 1) + max(-delta, 0)) / n
        out.append(100.0 if loss == 0 else 100 - 100 / (1 + gain / loss))
    return out  # out[i] belongs to values[n + i]


worst = {"SMA20": 0.0, "EMA12": 0.0, "EMA26": 0.0, "RSI14": 0.0}
for seed in range(50):
    rng = random.Random(seed)
    price, close = 50.0, []
    for _ in range(300):
        price *= 1 + rng.gauss(0.0003, 0.02)
        close.append(price)
    arr = np.array(close)
    for name, mine, theirs in (
        ("SMA20", sma_series(close, 20), talib.SMA(arr, 20)[19:]),
        ("EMA12", ema_series(close, 12), talib.EMA(arr, 12)[11:]),
        ("EMA26", ema_series(close, 26), talib.EMA(arr, 26)[25:]),
        ("RSI14", rsi_series(close), talib.RSI(arr, 14)[14:]),
    ):
        assert len(mine) == len(theirs), (name, len(mine), len(theirs))
        worst[name] = max(worst[name], float(np.max(np.abs(np.array(mine) - theirs))))
print("max |stdlib - TA-Lib| over every row of 50 series:", worst)
