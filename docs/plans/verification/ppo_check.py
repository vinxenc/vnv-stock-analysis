"""Scratch: can TA-Lib's PPO(matype=EMA) + EMA reproduce the plan's PPO histogram (SMA-seeded EMAs)?"""
import random
from statistics import fmean

import numpy as np
import talib


def ema_series(values, n):
    alpha = 2 / (n + 1)
    out = [fmean(values[:n])]
    for value in values[n:]:
        out.append(out[-1] + alpha * (value - out[-1]))
    return out


def hist_series(values):  # hist[i] belongs to values[33 + i]
    fast = ema_series(values, 12)[14:]
    slow = ema_series(values, 26)
    line = [(a - b) / b for a, b in zip(fast, slow)]
    signal = ema_series(line, 9)
    return [a - b for a, b in zip(line[8:], signal)]


rng = random.Random(7)
price, close = 50.0, []
for _ in range(300):
    price *= 1 + rng.gauss(0.0003, 0.02)
    close.append(price)
arr = np.array(close)

mine = np.array(hist_series(close))
ppo = talib.PPO(arr, 12, 26, 1) / 100  # matype=1 is EMA; TA-Lib returns percent, NaN-padded
line = ppo[25:]
hist = line - talib.EMA(line, 9)
theirs = hist[8:]
print("rows compared:", len(mine), len(theirs), "NaN in theirs:", int(np.isnan(theirs).sum()))
print("max |PPO hist| difference, stdlib vs talib.PPO+EMA:", float(np.max(np.abs(mine - theirs))))
print("talib.MACD (absolute) first non-NaN hist index:", int(np.argmax(~np.isnan(talib.MACD(arr, 12, 26, 9)[2]))))
print("talib.PPO first non-NaN index:", int(np.argmax(~np.isnan(ppo))))
