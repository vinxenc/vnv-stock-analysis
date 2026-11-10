from libs.analysis.indicators import PATTERNS, Flags, Indicators, Series, Values


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

    def ema(self, values: Values, window: int) -> Series:
        return self._constant(values)

    def rsi(self, values: Values, window: int = 14) -> Series:
        return self.rsi_series if self.rsi_series is not None else self._constant(values)

    def stddev(self, values: Values, window: int) -> Series:
        return self._constant(values)

    def ppo_histogram(self, values: Values, fast: int = 12, slow: int = 26, signal: int = 9) -> Series:
        return self._constant(values)

    def bullish_patterns(self, opens: Values, highs: Values, lows: Values, closes: Values) -> Flags:
        return {name: self.pattern_flags.get(name, [False] * len(closes)) for name in PATTERNS}
