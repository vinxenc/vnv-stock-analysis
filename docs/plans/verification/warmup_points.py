"""Scratch: warm-up error converted to SCORE POINTS through each indicator's ramp (stdlib only)."""
import random
from statistics import fmean


def ema_series(values, n):
    alpha = 2 / (n + 1)
    out = [fmean(values[:n])]
    for value in values[n:]:
        out.append(out[-1] + alpha * (value - out[-1]))
    return out


def hist_series(values):  # PPO histogram; hist[i] belongs to values[33 + i]
    fast = ema_series(values, 12)[14:]
    slow = ema_series(values, 26)
    line = [(a - b) / b for a, b in zip(fast, slow)]
    signal = ema_series(line, 9)
    return [a - b for a, b in zip(line[8:], signal)]


def rsi_series(values, n=14):  # out[i] belongs to values[n + i]
    deltas = [b - a for a, b in zip(values, values[1:])]
    gain = fmean(max(d, 0) for d in deltas[:n])
    loss = fmean(max(-d, 0) for d in deltas[:n])
    out = [100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)]
    for delta in deltas[n:]:
        gain = (gain * (n - 1) + max(delta, 0)) / n
        loss = (loss * (n - 1) + max(-delta, 0)) / n
        out.append(100.0 if loss == 0 else 100 - 100 / (1 + gain / loss))
    return out


def ramp(x, lo, hi):
    return min(max((x - lo) / (hi - lo), 0.0), 1.0)


def p8(values):  # RSI zone, 2 pts: 0 at <=40 -> full at 55, full to 70, 0 at >=85
    r = rsi_series(values)[-1]
    return 2 * (ramp(r, 40, 55) if r < 62.5 else 1 - ramp(r, 70, 85))


def p9(values):  # hist > 0, 4 pts, 0 -> 0.5% of price
    return 4 * ramp(hist_series(values)[-1], 0, 0.005)


def p10(values):  # hist rising vs 3 sessions ago, 3 pts, 0 -> 0.3%
    h = hist_series(values)
    return 3 * ramp(h[-1] - h[-4], 0, 0.003)


def p11(values):  # fresh bullish cross, 2 pts, only while hist > 0; full if <= 1 session, 0 after 6
    h = hist_series(values)
    if h[-1] <= 0:
        return 0.0
    age = 0
    while age < 6 and h[-1 - age] > 0:
        age += 1
    if age >= 6 and h[-7] > 0:
        return 0.0  # no cross inside the last 6 sessions
    return 2 * (1.0 if age <= 1 else max(0.0, 1 - (age - 1) / 5))


def pivots(values, k=3):
    return [i for i in range(k, len(values) - k) if values[i] < min(values[i - k:i]) and values[i] < min(values[i + 1:i + 1 + k])]


def p22(values):  # RSI bullish divergence (regular), 5 pts, no uptrend gate here
    rsi = rsi_series(values)  # rsi_at(idx) = rsi[idx - 14]
    n, t = len(values), len(values) - 1
    piv = [i for i in pivots(values) if t - 40 <= i <= t - 3 and i >= 14]
    if len(piv) < 2:
        return 0.0
    l2 = piv[-1]
    older = [i for i in piv[:-1] if l2 - i >= 5]
    if not older:
        return 0.0
    l1 = older[-1]
    r1, r2, rt = rsi[l1 - 14], rsi[l2 - 14], rsi[-1]
    if not (values[l2] <= values[l1] * 0.99 and r2 > r1 and r1 <= 45 and values[t] > values[l2] and rt > r2):
        return 0.0
    age = t - l2
    return 5 * ramp(r2 - r1, 0, 8) * (1.0 if age <= 10 else max(0.0, 1 - (age - 10) / 15))


def walk(seed, rows):
    rng = random.Random(seed)
    price, out = 50.0, []
    for _ in range(rows):
        price *= 1 + rng.gauss(0.0003, 0.02)
        out.append(price)
    return out


series = [walk(seed, 1500) for seed in range(300)]
indicators = {"#8 RSI zone": p8, "#9 hist>0": p9, "#10 hist rising": p10, "#11 fresh cross": p11, "#22 divergence": p22}
true = {name: [fn(s) for s in series] for name, fn in indicators.items()}
print("fire rate on random walks (points > 0):", {n: round(sum(v > 0 for v in vals) / len(vals), 2) for n, vals in true.items()})
print("\n99th-percentile |error| in POINTS vs a 1500-row run (300 series)")
grid = (45, 55, 61, 70, 80, 90, 100, 110, 130)
print("rows   " + "  ".join(f"{n:>16}" for n in indicators))
first = {n: None for n in indicators}
for length in grid:
    row = []
    for name, fn in indicators.items():
        errors = sorted(abs(fn(s[-length:]) - t) for s, t in zip(series, true[name]))
        p95 = errors[int(0.99 * len(errors)) - 1]
        row.append(p95)
        if first[name] is None and p95 <= 0.5:
            first[name] = length
    print(f"{length:<6} " + "  ".join(f"{p:16.3f}" for p in row))
print("\nfirst grid length with 99th-percentile error <= 0.5 point:", first)
