"""What every `Indicators` engine must satisfy. To add a library, put an instance in ENGINES: same cases."""

import pytest

from libs.indicators import PATTERNS, Indicators, TalibIndicators

ENGINES: list[Indicators] = [TalibIndicators()]


@pytest.fixture(params=ENGINES, ids=lambda engine: type(engine).__name__)
def engine(request: pytest.FixtureRequest) -> Indicators:
    return request.param


def test_sma_pads_the_start_with_none_and_accepts_plain_floats(engine: Indicators) -> None:
    assert engine.sma([1.0, 2.0, 3.0, 4.0], 3) == [None, None, 2.0, 3.0]


def test_ema_is_seeded_with_the_sma_of_the_first_window(engine: Indicators) -> None:
    # window 3: seed = mean(1, 2, 3) = 2; next = 2 + 0.5 * (4 - 2) = 3 (smoothing 2 / (3 + 1))
    assert engine.ema([1.0, 2.0, 3.0, 4.0], 3) == [None, None, 2.0, 3.0]


def test_rsi_of_a_series_that_only_rises_or_only_falls(engine: Indicators) -> None:
    assert engine.rsi([float(i) for i in range(1, 21)])[-1] == 100.0
    assert engine.rsi([float(i) for i in range(20, 0, -1)])[-1] == 0.0


def test_stddev_is_the_population_one(engine: Indicators) -> None:
    assert engine.stddev([1.0, 3.0], 2) == [None, 1.0]  # sqrt(((1 - 2) ** 2 + (3 - 2) ** 2) / 2)


def test_ppo_histogram_of_a_flat_series_is_zero_after_the_warm_up(engine: Indicators) -> None:
    histogram = engine.ppo_histogram([100.0] * 40)
    assert histogram[:33] == [None] * 33  # 26 rows for the slow EMA + 8 more for the signal EMA, minus one
    assert histogram[33:] == [0.0] * 7


def test_ppo_histogram_turns_positive_after_a_jump_and_is_a_fraction_of_price(engine: Indicators) -> None:
    histogram = engine.ppo_histogram([100.0] * 50 + [110.0])
    assert histogram[-1] is not None
    assert 0 < histogram[-1] < 0.1  # a fraction, not a percentage


def test_ppo_histogram_of_a_series_shorter_than_the_slow_window_has_no_value(engine: Indicators) -> None:
    assert engine.ppo_histogram([100.0] * 10) == [None] * 10


def test_one_output_per_input_row(engine: Indicators) -> None:
    values = [float(i) for i in range(1, 61)]
    for series in (engine.sma(values, 5), engine.ema(values, 5), engine.rsi(values), engine.stddev(values, 5)):
        assert len(series) == len(values)
    assert len(engine.ppo_histogram(values)) == len(values)


# Candle patterns: a fall, then the pattern on the last row. Only the two patterns that need no gap are pinned here;
# an engine may define the morning star and the piercing line with a gap (TA-Lib does).

FALL_OPEN = [110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0, 101.0, 100.0]
FALL_CLOSE = [109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0, 101.0, 100.0, 95.0]


Candles = tuple[list[float], list[float], list[float], list[float]]


def candles_ending_with(open_: float, close: float, low: float | None = None, high: float | None = None) -> Candles:
    opens, closes = FALL_OPEN + [open_], FALL_CLOSE + [close]
    highs = [max(o, c) + 0.2 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) - 0.2 for o, c in zip(opens, closes, strict=True)]
    highs[-1] = high if high is not None else highs[-1]
    lows[-1] = low if low is not None else lows[-1]
    return opens, highs, lows, closes


def test_bullish_patterns_answer_every_name_with_one_flag_per_row(engine: Indicators) -> None:
    opens, highs, lows, closes = candles_ending_with(95.0, 101.0)
    flags = engine.bullish_patterns(opens, highs, lows, closes)
    assert set(flags) == set(PATTERNS)
    assert all(len(values) == len(closes) for values in flags.values())


def test_bullish_engulfing_is_flagged_on_the_last_row_only(engine: Indicators) -> None:
    flags = engine.bullish_patterns(*candles_ending_with(95.0, 101.0))  # bearish candle, then a bullish one covering it
    assert flags["engulfing"][-1] is True
    assert not any(flags["engulfing"][:-1])


def test_a_hammer_after_a_fall_is_flagged(engine: Indicators) -> None:
    flags = engine.bullish_patterns(*candles_ending_with(95.0, 95.5, low=92.0, high=95.6))
    assert flags["hammer"][-1] is True


def test_bearish_patterns_are_not_reported(engine: Indicators) -> None:
    """A rise, then a bearish engulfing: TA-Lib answers a negative number, the contract is bullish only."""
    opens = [90.0 + i for i in range(11)] + [101.0]
    closes = [91.0 + i for i in range(11)] + [89.0]
    highs = [max(o, c) + 0.2 for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) - 0.2 for o, c in zip(opens, closes, strict=True)]
    assert not any(engine.bullish_patterns(opens, highs, lows, closes)["engulfing"])
