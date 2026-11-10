import datetime as dt

from libs.db.models import Price
from libs.indicators import Flags, Indicators, Series, Values

PATTERNS = ("engulfing", "hammer", "morning_star", "piercing")


class StubIndicators(Indicators):
    """An engine that answers what the test says: a fixed RSI series and fixed pattern flags, a constant elsewhere.

    It shows which engine a feature really used, and lets a test craft an RSI without hand-computing Wilder's smoothing.
    """

    def __init__(
        self, value: float = 0.0, rsi: Series | None = None, patterns: dict[str, list[bool]] | None = None
    ) -> None:
        self.value = value
        self.rsi_series = rsi
        self.pattern_flags = patterns or {}

    def _constant(self, values: Values) -> Series:
        return [self.value] * len(values)

    def sma(self, values: Values, window: int) -> Series:
        return self._constant(values)

    def rsi(self, values: Values, window: int = 14) -> Series:
        return self.rsi_series if self.rsi_series is not None else self._constant(values)

    def stddev(self, values: Values, window: int) -> Series:
        return self._constant(values)

    def ppo_histogram(self, values: Values, fast: int = 12, slow: int = 26, signal: int = 9) -> Series:
        return self._constant(values)

    def bullish_patterns(self, opens: Values, highs: Values, lows: Values, closes: Values) -> Flags:
        return {name: self.pattern_flags.get(name, [False] * len(closes)) for name in PATTERNS}


def make_rows(
    symbol: str, count: int, source: str = "A", daily_growth: float = 1.002, end: dt.date | None = None
) -> list[Price]:
    """`count` consecutive daily rows ending on `end`, the price growing `daily_growth` a day, volume 1000 + day."""
    end = end or dt.date(2026, 11, 10)
    rows = []
    for index in range(count):
        close = 10 * daily_growth**index
        rows.append(
            Price.model_validate(
                dict(
                    symbol=symbol,
                    source=source,
                    date=end - dt.timedelta(days=count - 1 - index),
                    open=close,
                    high=close * 1.01,
                    low=close * 0.99,
                    close=close,
                    volume=1000 + index,
                )
            )
        )
    return rows
