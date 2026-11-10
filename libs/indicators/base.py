"""The indicator library the analysis depends on, as an interface (like `PriceSource` for the price sources).

Features ask an `Indicators` for moving averages, RSI and so on; which library computes them is decided once, where the
engine is created (`scripts/vn_stock_analyze.py`). To change library, subclass `Indicators` in this package, export it
in `__init__.py`, and add it to `ENGINES` in `tests/libs/indicators/test_contract.py`.

Every method takes and returns plain lists of floats, one output per input row, the start padded with `None` until the
window is full. Whether a value is *trusted* (warm-up) is decided by the minimum rows of the scoring table, not here.
"""

from abc import ABC, abstractmethod

Values = list[float]
Series = list[float | None]
Flags = dict[str, list[bool]]

PATTERNS = ("engulfing", "hammer", "morning_star", "piercing")  # the bullish reversal patterns of indicator #23


class Indicators(ABC):
    @abstractmethod
    def sma(self, values: Values, window: int) -> Series:
        """Simple moving average."""

    @abstractmethod
    def ema(self, values: Values, window: int) -> Series:
        """Exponential moving average (smoothing 2 / (window + 1)), seeded with the SMA of the first window."""

    @abstractmethod
    def rsi(self, values: Values, window: int = 14) -> Series:
        """Wilder RSI, 0..100, seeded with the average of the first `window` changes."""

    @abstractmethod
    def stddev(self, values: Values, window: int) -> Series:
        """Population standard deviation (ddof 0) of each window."""

    @abstractmethod
    def ppo_histogram(self, values: Values, fast: int = 12, slow: int = 26, signal: int = 9) -> Series:
        """MACD normalised by price, as a fraction (0.005 = 0.5%).

        `ppo = (EMA fast - EMA slow) / EMA slow`, histogram = `ppo - EMA(ppo, signal)`.
        """

    @abstractmethod
    def bullish_patterns(self, opens: Values, highs: Values, lows: Values, closes: Values) -> Flags:
        """For each name in PATTERNS, one flag per row: the pattern is bullish and completes on that row.

        The engine's own pattern definitions apply (a library may require a gap for the morning star and the piercing
        line, which HOSE's opening auction almost never produces).
        """
