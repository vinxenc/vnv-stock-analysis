"""Shapes #22-#24 on hand-built series. The RSI and the pattern flags come from a stub engine, so each case is exact."""

import math

import pytest

from libs.analysis import patterns
from libs.analysis.features import Candles, Detection
from libs.indicators import TalibIndicators
from tests.libs.analysis.fakes import StubIndicators

N = 60


def test_pivot_lows_need_to_beat_three_sessions_on_each_side() -> None:
    assert patterns.pivot_lows([9, 9, 9, 1, 9, 9, 9]) == [3]
    assert patterns.pivot_lows([9, 9, 9, 1, 1, 9, 9, 9]) == []  # a tie is not a pivot
    assert patterns.pivot_lows([9, 9, 1, 9, 9]) == []  # too close to the edge to be confirmed
    assert patterns.pivot_lows([5.0] * 10) == []


# #22 RSI bullish divergence: flat 100, a dip to 90 at L1 and a dip to `l2_price` at L2; today is index 59


def divergence_candles(l1: int = 40, l2: int = 50, l2_price: float = 85.0, last: float = 100.0) -> Candles:
    close = [100.0] * N
    close[l1], close[l2], close[-1] = 90.0, l2_price, last
    return Candles(close, close, close, close, [1.0] * N)


def rsi_series(
    l1: float | None = 30, l2: float | None = 38, now: float | None = 50, l1_index: int = 40, l2_index: int = 50
) -> list[float | None]:
    series: list[float | None] = [50.0] * N
    series[l1_index], series[l2_index], series[-1] = l1, l2, now
    return series


def test_divergence_full_strength_when_rsi_gains_8_points_and_l2_is_recent() -> None:
    result = patterns.rsi_divergence(divergence_candles(), StubIndicators(rsi=rsi_series()))
    assert result == Detection(1.0, {"l1_sessions_ago": 19, "l1_rsi": 30, "l2_sessions_ago": 9, "l2_rsi": 38})


@pytest.mark.parametrize(
    ("l2_rsi", "l2_index", "strength"),
    [
        (34, 50, 0.5),  # a 4-point gain is half of 8
        (38, 45, (25 - 14) / 15),  # L2 is 14 sessions old: recency falls from 1 at 10 to 0 at 25
        (45, 50, 1.0),  # a 15-point gain is capped at 8
    ],
)
def test_divergence_strength_scales_with_the_rsi_gain_and_fades_with_age(
    l2_rsi: float, l2_index: int, strength: float
) -> None:
    candles = divergence_candles(l2=l2_index)
    result = patterns.rsi_divergence(candles, StubIndicators(rsi=rsi_series(l2=l2_rsi, l2_index=l2_index)))
    assert isinstance(result, Detection)
    assert result.strength == pytest.approx(strength)


@pytest.mark.parametrize(
    ("candles", "rsi"),
    [
        (divergence_candles(), rsi_series(l2=30)),  # RSI did not rise
        (divergence_candles(), rsi_series(l1=46, l2=50)),  # the earlier low came from a strong RSI
        (divergence_candles(l2_price=89.5), rsi_series()),  # the price drop is under 1%
        (divergence_candles(last=84.0), rsi_series()),  # price is back under L2
        (divergence_candles(), rsi_series(now=37)),  # RSI is back under L2
        (divergence_candles(l2=44), rsi_series(l2_index=44)),  # the lows are only 4 sessions apart
        (divergence_candles(), rsi_series(l1=None)),  # no RSI value at L1
        (divergence_candles(l1=15), rsi_series(l1_index=15)),  # L1 is 44 sessions old: outside the 40-session window
    ],
    ids=["rsi flat", "rsi high", "drop small", "price back", "rsi back", "too close", "no rsi", "too old"],
)
def test_divergence_is_zero_unless_every_condition_holds(candles: Candles, rsi: list[float | None]) -> None:
    assert patterns.rsi_divergence(candles, StubIndicators(rsi=rsi)) == 0.0


def test_divergence_needs_two_pivot_lows() -> None:
    flat = Candles([100.0] * N, [100.0] * N, [100.0] * N, [100.0] * N, [1.0] * N)
    assert patterns.rsi_divergence(flat, StubIndicators(rsi=[50.0] * N)) == 0.0  # none
    close = [100.0] * N
    close[50] = 85.0
    one = Candles(close, close, close, close, [1.0] * N)
    assert patterns.rsi_divergence(one, StubIndicators(rsi=[40.0] * N)) == 0.0  # one


# #23 bullish reversal candle pattern: after a fall, today is index 59 with the volume given


def pattern_candles(volume_today: float = 150.0, volume_before: float = 100.0, locked_today: bool = False) -> Candles:
    close = [100.0] * 53 + [100.0, 99.0, 98.0, 97.0, 96.5, 96.0, 98.0]  # fell ~4% over the 5 sessions before today
    high = [value + 1 for value in close]
    low = [value - 1 for value in close]
    if locked_today:
        high[-1] = low[-1] = close[-1]
    volume = [100.0] * 57 + [volume_before, volume_before, volume_today]
    return Candles(close, high, low, close, volume)


def flags(**at: int) -> dict[str, list[bool]]:
    """`engulfing=59` puts a flag on that row of N rows."""
    return {name: [index == row for index in range(N)] for name, row in at.items()}


def test_candle_pattern_scores_the_pattern_weight_with_full_volume_and_recency() -> None:
    result = patterns.candle_pattern(pattern_candles(), StubIndicators(patterns=flags(engulfing=59)))
    assert result == Detection(1.0, {"pattern": "engulfing", "sessions_ago": 0})
    hammer = patterns.candle_pattern(pattern_candles(), StubIndicators(patterns=flags(hammer=59)))
    assert hammer == Detection(0.7, {"pattern": "hammer", "sessions_ago": 0})


def test_candle_pattern_quiet_volume_and_older_patterns_count_less() -> None:
    engine = StubIndicators(patterns=flags(piercing=58))  # one session ago: 0.6; volume 100 < 1.2 x 100: 0.6
    result = patterns.candle_pattern(pattern_candles(), engine)
    assert isinstance(result, Detection)
    assert result.strength == pytest.approx(0.8 * 0.6 * 0.6)
    assert result.details == {"pattern": "piercing", "sessions_ago": 1}
    quiet = patterns.candle_pattern(pattern_candles(volume_today=100), StubIndicators(patterns=flags(engulfing=59)))
    assert isinstance(quiet, Detection) and quiet.strength == pytest.approx(0.6)
    two_ago = patterns.candle_pattern(pattern_candles(), StubIndicators(patterns=flags(morning_star=57)))
    assert isinstance(two_ago, Detection) and two_ago.strength == pytest.approx(1.0 * 0.3 * 0.6)


def test_candle_pattern_keeps_the_strongest_one() -> None:
    engine = StubIndicators(patterns=flags(hammer=59) | flags(engulfing=58))
    result = patterns.candle_pattern(pattern_candles(), engine)
    assert isinstance(result, Detection)
    assert result.details["pattern"] == "hammer"  # 0.7 today beats 1.0 x 0.6 x 0.6 yesterday


def test_candle_pattern_is_zero_without_a_flag_a_fall_or_a_range() -> None:
    assert patterns.candle_pattern(pattern_candles(), StubIndicators()) == 0.0
    flat = Candles([100.0] * N, [101.0] * N, [99.0] * N, [100.0] * N, [100.0] * N)
    assert patterns.candle_pattern(flat, StubIndicators(patterns=flags(engulfing=59))) == 0.0  # no fall before it
    locked = pattern_candles(locked_today=True)
    assert patterns.candle_pattern(locked, StubIndicators(patterns=flags(engulfing=59))) == 0.0  # high == low: skipped


def test_candle_pattern_runs_on_the_real_engine() -> None:
    """No crash and no pattern on a flat series: the TA-Lib adapter answers every name the feature asks for."""
    flat = Candles([100.0] * N, [101.0] * N, [99.0] * N, [100.0] * N, [100.0] * N)
    assert patterns.candle_pattern(flat, TalibIndicators()) == 0.0


# #24 descending trendline breakout. 75 rows; highs: flat 100 with pivot highs A (index 30, 120) and B (index 50, 110).
# The line through them is 120 x (110 / 120) ** ((i - 30) / 20): 114.9 at 40, 99.1 today (index 74).

M = 75
LINE_TODAY = 120 * (110 / 120) ** (44 / 20)


def line_candles(
    closes: dict[int, float] | None = None, volume_today: float = 200.0, extra_highs: dict[int, float] | None = None
) -> Candles:
    high = [100.0] * M
    high[30], high[50] = 120.0, 110.0
    for index, value in (extra_highs or {}).items():
        high[index] = value
    close = [99.0] * M
    for index, value in (closes or {}).items():
        close[index] = value
    low = [98.0] * M
    volume = [100.0] * (M - 1) + [volume_today]
    return Candles(close, high, low, close, volume)


def test_trendline_breakout_today_on_volume_with_two_touches() -> None:
    result = patterns.trendline_breakout(line_candles({74: 101.0}), StubIndicators())
    assert isinstance(result, Detection)
    assert result.strength == pytest.approx(1.0 * 1.0 * 0.7)  # today, volume 2x average, two touches
    assert result.details["anchor1_sessions_ago"] == 44 and result.details["anchor2_sessions_ago"] == 24
    assert result.details["touches"] == 2 and result.details["broke_sessions_ago"] == 0
    assert result.details["line_today"] == pytest.approx(LINE_TODAY)


def test_trendline_breakout_a_third_touch_and_an_older_breakout() -> None:
    third_touch = line_candles({74: 101.0}, extra_highs={40: 114.5})  # a pivot high within 1% of the line
    result = patterns.trendline_breakout(third_touch, StubIndicators())
    assert isinstance(result, Detection) and result.strength == pytest.approx(1.0) and result.details["touches"] == 3
    assert result.details["anchor1_sessions_ago"] == 44  # the longest line wins the tie on touches
    yesterday = patterns.trendline_breakout(line_candles({73: 101.0, 74: 101.0}), StubIndicators())
    assert isinstance(yesterday, Detection) and yesterday.strength == pytest.approx(
        0.6 * 0.6 * 0.7
    )  # volume is the breakout day's: 100, not 1.5x
    assert yesterday.details["broke_sessions_ago"] == 1
    quiet = patterns.trendline_breakout(line_candles({74: 101.0}, volume_today=100.0), StubIndicators())
    assert isinstance(quiet, Detection) and quiet.strength == pytest.approx(0.6 * 0.7)


@pytest.mark.parametrize(
    ("candles", "why"),
    [
        (line_candles(), "no close above the line"),
        (line_candles({74: 120.0}), "ran more than 7% above the line"),
        (line_candles({73: 101.0, 74: 98.0}), "fell back under the line"),
        (line_candles({i: 103.0 for i in range(70, 75)}), "already above the line before the last 3 sessions"),
        (line_candles({74: 101.0}, extra_highs={40: 125.0, 41: 125.0}), "a high pokes through the line"),
        (line_candles({74: 101.0}, extra_highs={30: 110.0, 50: 120.0}), "the line rises"),
        (line_candles({74: 101.0}, extra_highs={36: 105.0, 50: 100.0}), "anchors too close: 6 sessions"),
        (line_candles({74: 101.0}, extra_highs={50: 100.0, 70: 110.0}), "the second pivot is not confirmed yet"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_trendline_breakout_is_zero_unless_a_valid_line_was_just_broken(candles: Candles, why: str) -> None:
    assert patterns.trendline_breakout(candles, StubIndicators()) == 0.0, why


def test_trendline_log_line_matches_the_closed_form() -> None:
    assert math.isclose(LINE_TODAY, 99.1, abs_tol=0.1)
