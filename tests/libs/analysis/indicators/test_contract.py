"""What every `Indicators` engine must satisfy. To add a library, put an instance in ENGINES: same cases."""

import pytest

from libs.analysis.indicators import Indicators, TalibIndicators

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
