"""Raw features: one small function per indicator, `Candles -> number or None`. They know nothing about points.

Rows are sessions, ascending; index -1 is the session analysed. A function may assume the history is long enough
(the minimum rows of the scoring table are checked before it is called); `None` means "cannot be computed" (a zero
average, a candle with no range). A feature that needs a moving average, RSI and so on takes the `Indicators` engine
as its second parameter and never imports a library; the others only look at the candles. Conventions follow the
plan's minimum-rows column: "N + 1 rows" means N sessions before today, or N one-day changes.
"""

from dataclasses import dataclass, field

from libs.db.models import Price
from libs.indicators import Indicators

UP_DOWN_CAP = 10.0  # up/down volume ratio when nothing was sold: well above the ramp's top, finite for the JSON
CROSS_AGE_CAP = 6.0  # a MACD cross older than this scores nothing, so the age stops counting here


@dataclass(frozen=True)
class Detection:
    """What a shape feature (#22-#24) found: its strength, 0..1, and the facts behind it for the output."""

    strength: float
    details: dict[str, float | int | str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class Candles:
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    volume: list[float]

    @classmethod
    def from_prices(cls, rows: list[Price]) -> "Candles":
        return cls(
            [row.open for row in rows],
            [row.high for row in rows],
            [row.low for row in rows],
            [row.close for row in rows],
            [float(row.volume) for row in rows],
        )

    def __len__(self) -> int:
        return len(self.close)


def _last(values: list[float | None]) -> float | None:
    return values[-1]


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _is_up(candles: Candles, index: int) -> bool:
    return candles.close[index] > candles.close[index - 1]


# Trend (#1-#5)


def close_vs_sma(candles: Candles, engine: Indicators, window: int) -> float | None:
    """#1, #2, #5, #19: close / SMA(window) - 1."""
    average = _last(engine.sma(candles.close, window))
    return None if average is None else candles.close[-1] / average - 1


def sma_short_above_long(candles: Candles, engine: Indicators, short: int = 20, long: int = 50) -> float | None:
    """#3: 1.0 when SMA20 > SMA50, else 0.0."""
    short_average = _last(engine.sma(candles.close, short))
    long_average = _last(engine.sma(candles.close, long))
    if short_average is None or long_average is None:
        return None
    return float(short_average > long_average)


def sma_change(candles: Candles, engine: Indicators, window: int = 50, lag: int = 10) -> float | None:
    """#4: SMA(window) today / SMA(window) `lag` sessions ago - 1."""
    averages = engine.sma(candles.close, window)
    now, before = averages[-1], averages[-1 - lag]
    return None if now is None or before is None else now / before - 1


# Momentum (#6-#11)


def period_return(candles: Candles, sessions: int) -> float:
    """#6, #7: close today / close `sessions` rows ago - 1 (ranked across the shortlist, see scoring)."""
    return candles.close[-1] / candles.close[-1 - sessions] - 1


def rsi_value(candles: Candles, engine: Indicators, window: int = 14) -> float | None:
    """#8: Wilder RSI of today."""
    return _last(engine.rsi(candles.close, window))


def ppo_histogram_now(candles: Candles, engine: Indicators) -> float | None:
    """#9: PPO histogram of today (fraction of price)."""
    return _last(engine.ppo_histogram(candles.close))


def ppo_histogram_change(candles: Candles, engine: Indicators, lag: int = 3) -> float | None:
    """#10: PPO histogram today - `lag` sessions ago."""
    histogram = engine.ppo_histogram(candles.close)
    now, before = histogram[-1], histogram[-1 - lag]
    return None if now is None or before is None else now - before


def ppo_cross_age(candles: Candles, engine: Indicators) -> float:
    """#11: sessions since the PPO histogram turned positive (0 = today), CROSS_AGE_CAP if it is not positive now."""
    histogram = engine.ppo_histogram(candles.close)
    age = 0
    while age < len(histogram) and (value := histogram[-1 - age]) is not None and value > 0:
        age += 1
    return min(float(age - 1), CROSS_AGE_CAP) if age else CROSS_AGE_CAP


# Money flow (#12-#15)


def up_day_volume_ratio(candles: Candles, window: int = 20) -> float | None:
    """#12: today's volume / average volume of the `window` sessions before today; 0 when today is not an up day."""
    average = mean(candles.volume[-1 - window : -1])
    if average == 0:
        return None
    return candles.volume[-1] / average if _is_up(candles, len(candles) - 1) else 0.0


def up_down_volume_ratio(candles: Candles, window: int = 20) -> float | None:
    """#13: volume on up days / volume on down days over the last `window` one-day changes (capped, None if no move)."""
    indexes = range(len(candles) - window, len(candles))
    up = sum(candles.volume[index] for index in indexes if _is_up(candles, index))
    down = sum(candles.volume[index] for index in indexes if candles.close[index] < candles.close[index - 1])
    if down == 0:
        return UP_DOWN_CAP if up > 0 else None
    return min(up / down, UP_DOWN_CAP)


def turnover_ratio(candles: Candles, short: int = 5, long: int = 20) -> float | None:
    """#14: average close x volume of the last `short` sessions / of the last `long` sessions (today included)."""
    turnover = [close * volume for close, volume in zip(candles.close, candles.volume, strict=True)]
    average = mean(turnover[-long:])
    return None if average == 0 else mean(turnover[-short:]) / average


def close_location(candles: Candles) -> float | None:
    """#15: (close - low) / (high - low) of today; None when high == low (locked at the ceiling or floor)."""
    span = candles.high[-1] - candles.low[-1]
    return None if span == 0 else (candles.close[-1] - candles.low[-1]) / span


# Position (#16-#18)


def close_vs_prior_high(candles: Candles, window: int = 20) -> float:
    """#16: close / highest high of the `window` sessions before today."""
    return candles.close[-1] / max(candles.high[-1 - window : -1])


def close_vs_high(candles: Candles, window: int = 250) -> float:
    """#17: close / highest high of the last `window` sessions (today included)."""
    return candles.close[-1] / max(candles.high[-window:])


def higher_lows(candles: Candles, window: int = 10) -> float:
    """#18: lowest low of the last `window` sessions / lowest low of the `window` before - 1."""
    return min(candles.low[-window:]) / min(candles.low[-2 * window : -window]) - 1


# Risk (#19-#21); #19 is close_vs_sma(window=20)


def return_volatility(candles: Candles, engine: Indicators, window: int = 20) -> float | None:
    """#20: standard deviation of the last `window` daily returns (ranked, lower is better)."""
    returns = [candles.close[index] / candles.close[index - 1] - 1 for index in range(1, len(candles))]
    return _last(engine.stddev(returns, window))


def no_distribution_day(candles: Candles, lookback: int = 10, window: int = 20) -> float | None:
    """#21: 1.0, or 0.0 if a session of the last `lookback` fell >= 3% on volume >= 1.5x the `window` average."""
    average = mean(candles.volume[-window:])
    if average == 0:
        return None
    for index in range(len(candles) - lookback, len(candles)):
        fell = candles.close[index] / candles.close[index - 1] - 1 <= -0.03
        if fell and candles.volume[index] >= 1.5 * average:
            return 0.0
    return 1.0
