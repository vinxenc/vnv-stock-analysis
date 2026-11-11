"""The scoring table: one row per indicator (id, theme, maximum, minimum rows, raw feature, curve).

Changing a weight or a threshold edits one row. Features live in `features.py`, gates and flags in `gates.py`.
Every number here is a placeholder to be tuned once the real score distribution is visible.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Literal

from libs.analysis import features, patterns
from libs.analysis.features import Candles, Curve, Detection, ramp
from libs.analysis.gates import uptrend_gate
from libs.analysis.models import IndicatorResult, IndicatorStatus, Theme
from libs.indicators import Indicators

Raw = float | Detection | None  # a number, what a shape feature found (#22-#24), or None = cannot be computed
Feature = Callable[[Candles, Indicators], Raw]  # candles and the engine -> raw


def trapezoid(zero_low: float, full_low: float, full_high: float, zero_high: float) -> Curve:
    """Full inside [full_low, full_high], ramping to 0 at `zero_low` and `zero_high`."""
    up, down = ramp(zero_low, full_low), ramp(zero_high, full_high)
    return lambda value: min(up(value), down(value))


def percentile_rank(value: float, values: list[float]) -> float:
    """Position of `value` among `values` (it is one): 0 lowest, 1 highest, ties share the middle, alone = 0.5."""
    if len(values) == 1:
        return 0.5
    below = sum(other < value for other in values)
    equal = sum(other == value for other in values)
    return (below + (equal - 1) / 2) / (len(values) - 1)


@dataclass(frozen=True)
class Indicator:
    id: int
    theme: Theme
    max_points: float
    min_rows: int  # fewer rows than this: the indicator is unavailable (warm-up and lookback)
    raw_name: str  # key of the raw value in the output
    feature: Feature
    curve: Curve = ramp(0, 1)
    rank: Literal["high", "low"] | None = None  # ranked across the shortlist instead of using the curve
    uptrend_only: bool = False  # counts only while SMA50 is not falling (gate on #4)


def metadata() -> dict:
    """The weights behind a score, stored with every ranking row: they are placeholders to tune, so a stored score must
    say which weights produced it. The curves' thresholds are closures and are not included."""
    return {
        "weights": [
            {"id": i.id, "theme": i.theme, "name": i.raw_name, "max_points": i.max_points, "min_rows": i.min_rows}
            for i in INDICATORS
        ]
    }


def pure(feature: Callable[[Candles], float | None]) -> Feature:
    """A feature that only looks at the candles: drop the engine argument the runner passes."""
    return lambda candles, _engine: feature(candles)


INDICATORS = [
    Indicator(1, Theme.TREND, 3, 20, "close_vs_sma20", partial(features.close_vs_sma, window=20), ramp(0, 0.03)),
    Indicator(2, Theme.TREND, 5, 50, "close_vs_sma50", partial(features.close_vs_sma, window=50), ramp(0, 0.05)),
    Indicator(3, Theme.TREND, 4, 50, "sma20_above_sma50", features.sma_short_above_long),
    Indicator(4, Theme.TREND, 5, 60, "sma50_change", features.sma_change, ramp(0, 0.02)),
    Indicator(5, Theme.TREND, 6, 200, "close_vs_sma200", partial(features.close_vs_sma, window=200), ramp(0, 0.10)),
    Indicator(6, Theme.MOMENTUM, 5, 21, "return_20", pure(partial(features.period_return, sessions=20)), rank="high"),
    Indicator(7, Theme.MOMENTUM, 4, 61, "return_60", pure(partial(features.period_return, sessions=60)), rank="high"),
    Indicator(8, Theme.MOMENTUM, 2, 45, "rsi14", features.rsi_value, trapezoid(40, 55, 70, 85)),
    Indicator(9, Theme.MOMENTUM, 4, 70, "ppo_histogram", features.ppo_histogram_now, ramp(0, 0.005)),
    Indicator(10, Theme.MOMENTUM, 3, 55, "ppo_histogram_change", features.ppo_histogram_change, ramp(0, 0.003)),
    Indicator(11, Theme.MOMENTUM, 2, 70, "sessions_since_cross", features.ppo_cross_age, ramp(6, 1)),
    Indicator(12, Theme.MONEY_FLOW, 8, 21, "volume_vs_average", pure(features.up_day_volume_ratio), ramp(1, 2)),
    Indicator(13, Theme.MONEY_FLOW, 7, 21, "up_down_volume_ratio", pure(features.up_down_volume_ratio), ramp(1, 2)),
    Indicator(14, Theme.MONEY_FLOW, 5, 21, "turnover_ratio", pure(features.turnover_ratio), ramp(1, 1.5)),
    Indicator(15, Theme.MONEY_FLOW, 5, 1, "close_location", pure(features.close_location), ramp(0.5, 0.9)),
    Indicator(16, Theme.POSITION, 2, 21, "close_vs_prior_high", pure(features.close_vs_prior_high), ramp(0.93, 1)),
    Indicator(17, Theme.POSITION, 2, 250, "close_vs_250_high", pure(features.close_vs_high), ramp(0.75, 0.95)),
    Indicator(18, Theme.POSITION, 4, 20, "higher_lows", pure(features.higher_lows), ramp(0, 0.03)),
    Indicator(19, Theme.RISK, 4, 20, "close_vs_sma20", partial(features.close_vs_sma, window=20), ramp(0.18, 0.08)),
    Indicator(20, Theme.RISK, 3, 21, "return_volatility", features.return_volatility, rank="low"),
    Indicator(21, Theme.RISK, 3, 21, "no_distribution_day", pure(features.no_distribution_day)),
    Indicator(22, Theme.REVERSAL, 5, 60, "rsi_divergence", patterns.rsi_divergence, uptrend_only=True),
    Indicator(23, Theme.REVERSAL, 5, 60, "candle_pattern", patterns.candle_pattern, uptrend_only=True),
    Indicator(24, Theme.POSITION, 4, 70, "trendline_breakout", patterns.trendline_breakout),
]
assert sum(indicator.max_points for indicator in INDICATORS) == 100
SMA50_CHANGE = 4  # the raw value the uptrend gate reads


def raw_values(candles: Candles, engine: Indicators) -> dict[int, Raw]:
    """Raw value of every indicator; None = unavailable (too few rows, or the feature cannot be computed)."""
    return {
        indicator.id: indicator.feature(candles, engine) if len(candles) >= indicator.min_rows else None
        for indicator in INDICATORS
    }


def percentile_ranks(raw_by_symbol: dict[str, dict[int, Raw]]) -> dict[str, dict[int, float]]:
    """Second pass for the ranked indicators (#6, #7, #20): rank each symbol among the symbols that have a value."""
    ranks: dict[str, dict[int, float]] = {symbol: {} for symbol in raw_by_symbol}
    for indicator in INDICATORS:
        if indicator.rank is None:
            continue
        values = {symbol: raw[indicator.id] for symbol, raw in raw_by_symbol.items() if raw[indicator.id] is not None}
        for symbol, value in values.items():
            ranks[symbol][indicator.id] = percentile_rank(value, list(values.values()))
    return ranks


def _result(
    indicator: Indicator,
    status: IndicatorStatus,
    points: float = 0,
    raw: dict[str, float | int | str | None] | None = None,
) -> IndicatorResult:
    return IndicatorResult(
        id=indicator.id,
        theme=indicator.theme,
        status=status,
        points=points,
        max_points=indicator.max_points,
        raw=raw or {},
    )


def score_indicators(raw: dict[int, Raw], ranks: dict[int, float]) -> list[IndicatorResult]:
    """Points of every indicator of one symbol. `ranks` = that symbol's entry of `percentile_ranks`."""
    sma50_change = raw[SMA50_CHANGE]
    gate = uptrend_gate(sma50_change if isinstance(sma50_change, float) else None)
    results = []
    for indicator in INDICATORS:
        value = raw[indicator.id]
        if value is None:
            results.append(_result(indicator, IndicatorStatus.UNAVAILABLE))
        elif indicator.uptrend_only and gate is not None:
            results.append(_result(indicator, gate, raw={"sma50_change": sma50_change}))
        else:
            number, details = (value.strength, value.details) if isinstance(value, Detection) else (value, {})
            facts = {indicator.raw_name: number, **details}
            if indicator.rank is None:
                share = indicator.curve(number)
            else:
                rank = ranks[indicator.id]
                facts["percentile"] = rank
                share = rank if indicator.rank == "high" else 1 - rank
            results.append(_result(indicator, IndicatorStatus.SCORED, indicator.max_points * share, facts))
    return results
