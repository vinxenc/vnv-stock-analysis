"""One hand-computed series per feature. Expected values are worked out by hand, never taken from TA-Lib."""

import pytest

from libs.analysis import features
from libs.analysis.features import Candles
from libs.db.models import Price
from libs.indicators import TalibIndicators

ENGINE = TalibIndicators()


def candles(
    close: list[float],
    high: list[float] | None = None,
    low: list[float] | None = None,
    volume: list[float] | None = None,
) -> Candles:
    return Candles(close, high or close, low or close, close, volume or [1000.0] * len(close))


def test_candles_from_prices_turns_volume_into_float() -> None:
    row = Price.model_validate(
        dict(symbol="A", source="S", date="2026-11-10", open=1, high=3, low=1, close=2, volume=7)
    )
    result = Candles.from_prices([row])
    assert (result.open, result.high, result.low, result.close, result.volume) == ([1], [3], [1], [2], [7.0])
    assert isinstance(result.volume[0], float)
    assert len(result) == 1


# Trend


def test_close_vs_sma() -> None:
    assert features.close_vs_sma(candles([1, 2, 3, 4, 5]), ENGINE, 3) == pytest.approx(
        5 / 4 - 1
    )  # SMA3 = (3 + 4 + 5) / 3
    assert features.close_vs_sma(candles([1, 2]), ENGINE, 3) is None


def test_sma_short_above_long() -> None:
    rising = candles([float(i) for i in range(1, 51)])  # SMA20 = 40.5, SMA50 = 25.5
    falling = candles([float(i) for i in range(50, 0, -1)])  # SMA20 = 10.5, SMA50 = 25.5
    assert features.sma_short_above_long(rising, ENGINE) == 1.0
    assert features.sma_short_above_long(falling, ENGINE) == 0.0
    assert features.sma_short_above_long(candles([1.0] * 30), ENGINE) is None


def test_sma_change() -> None:
    # SMA3 today = (4 + 5 + 6) / 3 = 5, two sessions ago = (2 + 3 + 4) / 3 = 3
    assert features.sma_change(candles([1, 2, 3, 4, 5, 6]), ENGINE, window=3, lag=2) == pytest.approx(5 / 3 - 1)
    assert features.sma_change(candles([1, 2, 3, 4]), ENGINE, window=3, lag=2) is None


def test_period_return() -> None:
    assert features.period_return(candles([1, 2, 4]), 2) == 3.0  # 4 / 1 - 1
    assert features.period_return(candles([4, 2, 1]), 1) == -0.5


# Momentum


def test_rsi_value() -> None:
    assert features.rsi_value(candles([float(i) for i in range(1, 21)]), ENGINE) == 100.0
    assert features.rsi_value(candles([1.0, 2.0]), ENGINE) is None


def test_ppo_histogram_now_and_change() -> None:
    flat = candles([100.0] * 50)
    jump = candles([100.0] * 50 + [110.0] * 3)
    assert features.ppo_histogram_now(flat, ENGINE) == 0.0
    assert features.ppo_histogram_now(jump, ENGINE) > 0
    assert features.ppo_histogram_change(flat, ENGINE) == 0.0
    assert features.ppo_histogram_change(jump, ENGINE) > 0  # the histogram grew over the last 3 sessions
    assert features.ppo_histogram_now(candles([100.0] * 10), ENGINE) is None
    assert features.ppo_histogram_change(candles([100.0] * 10), ENGINE) is None


@pytest.mark.parametrize(("held", "age"), [(1, 0), (2, 1), (4, 3), (8, 6)])  # a jump, then `held - 1` flat sessions
def test_ppo_cross_age_counts_sessions_since_the_histogram_turned_positive(held: int, age: int) -> None:
    assert features.ppo_cross_age(candles([100.0] * 50 + [110.0] * held), ENGINE) == age  # 8 sessions: capped at 6


def test_ppo_cross_age_is_the_cap_while_the_histogram_is_not_positive() -> None:
    assert features.ppo_cross_age(candles([100.0] * 50), ENGINE) == features.CROSS_AGE_CAP  # exactly 0
    assert features.ppo_cross_age(candles([100.0] * 50 + [90.0]), ENGINE) == features.CROSS_AGE_CAP  # negative
    assert features.ppo_cross_age(candles([100.0] * 10), ENGINE) == features.CROSS_AGE_CAP  # nothing yet


# Money flow


def test_up_day_volume_ratio() -> None:
    up = candles([10, 10, 11], volume=[100, 100, 200])  # prior 2 sessions average 100
    down = candles([10, 11, 10], volume=[100, 100, 200])
    assert features.up_day_volume_ratio(up, window=2) == 2.0
    assert features.up_day_volume_ratio(down, window=2) == 0.0
    assert features.up_day_volume_ratio(candles([10, 10, 11], volume=[0, 0, 5]), window=2) is None


def test_up_down_volume_ratio() -> None:
    # last 3 changes: 11 up (100), 10 down (50), 12 up (300): up 400 / down 50
    mixed = candles([10, 11, 10, 12], volume=[999, 100, 50, 300])
    assert features.up_down_volume_ratio(mixed, window=3) == 8.0
    assert features.up_down_volume_ratio(candles([10, 11, 12], volume=[1, 5, 5]), window=2) == features.UP_DOWN_CAP
    assert features.up_down_volume_ratio(candles([10, 10, 10]), window=2) is None  # nothing moved
    assert features.up_down_volume_ratio(candles([10, 11, 10], volume=[1, 3, 2]), window=2) == 1.5
    assert features.up_down_volume_ratio(candles([10, 11, 10], volume=[1, 99999, 1]), window=2) == features.UP_DOWN_CAP


def test_turnover_ratio() -> None:
    result = candles([1, 1, 1, 1], volume=[1, 1, 1, 5])  # turnover = volume: last 2 average 3, last 4 average 2
    assert features.turnover_ratio(result, short=2, long=4) == 1.5
    assert features.turnover_ratio(candles([1, 1], volume=[0, 0]), short=1, long=2) is None


def test_close_location() -> None:
    assert features.close_location(candles([11], high=[12], low=[8])) == 0.75
    assert features.close_location(candles([9], high=[9], low=[9])) is None  # locked at the ceiling or floor


# Position


def test_close_vs_prior_high_excludes_today() -> None:
    result = candles([5, 6, 7, 8], high=[9, 7, 6, 50])  # prior 3 highs 9, 7, 6: today's high 50 is ignored
    assert features.close_vs_prior_high(result, window=3) == pytest.approx(8 / 9)


def test_close_vs_high_includes_today() -> None:
    result = candles([1, 1, 1, 6], high=[99, 7, 6, 8])  # last 3 highs 7, 6, 8: the 99 is outside the window
    assert features.close_vs_high(result, window=3) == 6 / 8


def test_higher_lows() -> None:
    assert features.higher_lows(candles([9, 9, 9, 9], low=[5, 6, 7, 8]), window=2) == pytest.approx(7 / 5 - 1)
    assert features.higher_lows(candles([9, 9, 9, 9], low=[7, 8, 5, 6]), window=2) == pytest.approx(5 / 7 - 1)


# Risk


def test_return_volatility() -> None:
    result = candles([100, 110, 99, 108.9])  # returns +10%, -10%, +10%: mean 1/30, population std = sqrt(0.00889)
    assert features.return_volatility(result, ENGINE, window=3) == pytest.approx(0.0942809)
    assert features.return_volatility(candles([100, 110]), ENGINE, window=3) is None
    assert features.return_volatility(candles([5.0] * 5), ENGINE, window=3) == 0.0


def test_no_distribution_day() -> None:
    quiet = candles([100, 100, 100, 95], volume=[100, 100, 100, 150])  # -5%, but 150 < 1.5 x 116.7
    heavy = candles([100, 100, 100, 95], volume=[100, 100, 100, 300])  # -5% on 300 >= 1.5 x 166.7
    small_drop = candles([100, 100, 100, 98], volume=[100, 100, 100, 300])  # -2%: not a distribution day
    assert features.no_distribution_day(quiet, lookback=2, window=3) == 1.0
    assert features.no_distribution_day(heavy, lookback=2, window=3) == 0.0
    assert features.no_distribution_day(small_drop, lookback=2, window=3) == 1.0
    assert features.no_distribution_day(candles([1, 1, 1], volume=[0, 0, 0]), lookback=2, window=3) is None
