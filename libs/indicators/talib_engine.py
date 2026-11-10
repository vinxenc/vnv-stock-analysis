"""TA-Lib implementation of `Indicators`. The only module that imports TA-Lib and numpy."""

import math

import numpy as np
import talib

from .base import Flags, Indicators, Series, Values


def _clean(array: np.ndarray) -> Series:
    return [None if math.isnan(value) else float(value) for value in array]


def _array(values: Values) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)  # TA-Lib rejects ints (volume) and lists


class TalibIndicators(Indicators):
    def sma(self, values: Values, window: int) -> Series:
        return _clean(talib.SMA(_array(values), window))

    def ema(self, values: Values, window: int) -> Series:
        return _clean(talib.EMA(_array(values), window))

    def rsi(self, values: Values, window: int = 14) -> Series:
        return _clean(talib.RSI(_array(values), window))

    def stddev(self, values: Values, window: int) -> Series:
        return _clean(talib.STDDEV(_array(values), window))

    def ppo_histogram(self, values: Values, fast: int = 12, slow: int = 26, signal: int = 9) -> Series:
        """Not `talib.MACD`: that one is absolute and seeds its fast EMA differently."""
        ppo = _array(talib.PPO(_array(values), fast, slow, matype=1)) / 100
        first = next((index for index, value in enumerate(ppo) if not math.isnan(value)), len(ppo))
        histogram = np.full(len(ppo), np.nan)
        if first < len(ppo):
            histogram[first:] = ppo[first:] - talib.EMA(ppo[first:], signal)
        return _clean(histogram)

    def bullish_patterns(self, opens: Values, highs: Values, lows: Values, closes: Values) -> Flags:
        """TA-Lib answers 100 / 80 for bullish, -100 / -80 for bearish, 0 for none: keep the positive ones."""
        candles = (_array(opens), _array(highs), _array(lows), _array(closes))
        functions = {
            "engulfing": talib.CDLENGULFING,
            "hammer": talib.CDLHAMMER,
            "morning_star": talib.CDLMORNINGSTAR,
            "piercing": talib.CDLPIERCING,
        }
        return {name: [bool(value > 0) for value in function(*candles)] for name, function in functions.items()}
