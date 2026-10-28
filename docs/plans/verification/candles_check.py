"""Scratch: does TA-Lib's candle recognition fire on gap-free patterns (HOSE opens through ATO, so gaps are rare)?"""
import numpy as np
import talib


def downtrend() -> list[tuple[float, float, float, float]]:
    bars, price = [], 100.0
    for _ in range(15):
        bars.append((price, price + 0.3, price - 1.3, price - 1.0))  # open, high, low, close
        price -= 1.0
    return bars  # last close = 85


def run(name: str, tail: list[tuple[float, float, float, float]]) -> dict[str, int]:
    bars = downtrend() + tail
    o, h, low, c = (np.array(column, dtype=float) for column in zip(*bars))
    return {
        "morning_star": int(talib.CDLMORNINGSTAR(o, h, low, c)[-1]),
        "piercing": int(talib.CDLPIERCING(o, h, low, c)[-1]),
        "engulfing": int(talib.CDLENGULFING(o, h, low, c)[-1]),
        "hammer": int(talib.CDLHAMMER(o, h, low, c)[-1]),
    }


cases = {
    "morning star WITH body gap": [(85, 85.2, 79.8, 80), (78.5, 79.2, 78.2, 78.8), (79.0, 84.3, 78.9, 84)],
    "morning star NO gap": [(85, 85.2, 79.8, 80), (80, 80.3, 79.4, 79.7), (79.9, 84.3, 79.8, 84)],
    "piercing WITH gap below low": [(85, 85.2, 79.8, 80), (79, 83.6, 78.8, 83.5)],
    "piercing NO gap (open = prev close)": [(85, 85.2, 79.8, 80), (80, 83.6, 79.8, 83.5)],
    "bullish engulfing (no gap needed)": [(81, 81.2, 79.8, 80), (79.8, 81.7, 79.7, 81.6)],
    "hammer": [(80, 80.1, 78.4, 80.6)],
}
for name, tail in cases.items():
    print(f"{name:<40}", run(name, tail))
