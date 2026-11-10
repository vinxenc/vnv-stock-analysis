import pytest

from libs.analysis import scoring
from libs.analysis.features import Candles, Detection
from libs.analysis.models import IndicatorResult, IndicatorStatus, Theme
from libs.analysis.scoring import INDICATORS, percentile_rank, ramp, trapezoid
from libs.indicators import TalibIndicators
from tests.libs.analysis.fakes import StubIndicators

ENGINE = TalibIndicators()


def test_table_is_complete_and_adds_up_to_100() -> None:
    assert [indicator.id for indicator in INDICATORS] == list(range(1, 25))
    assert sum(indicator.max_points for indicator in INDICATORS) == 100
    totals = {theme: sum(item.max_points for item in INDICATORS if item.theme == theme) for theme in Theme}
    assert totals == {
        Theme.TREND: 23,
        Theme.MOMENTUM: 20,
        Theme.MONEY_FLOW: 25,
        Theme.POSITION: 12,
        Theme.RISK: 10,
        Theme.REVERSAL: 10,
    }


@pytest.mark.parametrize(
    ("value", "share"),
    [(-1, 0.0), (0, 0.0), (0.015, 0.5), (0.03, 1.0), (9, 1.0)],  # ramp(0, 0.03): clamped both ends
)
def test_ramp_clamps(value: float, share: float) -> None:
    assert ramp(0, 0.03)(value) == pytest.approx(share)


@pytest.mark.parametrize(("value", "share"), [(0.0, 1.0), (0.08, 1.0), (0.13, 0.5), (0.18, 0.0), (0.5, 0.0)])
def test_ramp_with_start_above_end_prefers_lower_values(value: float, share: float) -> None:
    assert ramp(0.18, 0.08)(value) == pytest.approx(share)  # #19: full at <= +8%, none at >= +18%


@pytest.mark.parametrize(
    ("rsi", "share"), [(30, 0), (40, 0), (47.5, 0.5), (55, 1), (62, 1), (70, 1), (77.5, 0.5), (85, 0), (95, 0)]
)
def test_trapezoid_for_the_rsi_zone(rsi: float, share: float) -> None:
    assert trapezoid(40, 55, 70, 85)(rsi) == pytest.approx(share)


def test_percentile_rank() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert [percentile_rank(value, values) for value in values] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert percentile_rank(7.0, [7.0]) == 0.5  # alone in the shortlist
    assert percentile_rank(2.0, [1.0, 2.0, 2.0, 3.0]) == pytest.approx(0.5)  # ties share the middle: (1 + 0.5) / 3
    assert percentile_rank(1.0, [1.0, 1.0]) == 0.5


def candles(count: int, close: float = 100.0) -> Candles:
    return Candles([close] * count, [close] * count, [close] * count, [close] * count, [1000.0] * count)


def test_minimum_rows_decide_availability() -> None:
    assert scoring.raw_values(candles(0), ENGINE).keys() == set(range(1, 25))
    assert all(value is None for value in scoring.raw_values(candles(0), ENGINE).values())
    available = {id_: value is not None for id_, value in scoring.raw_values(candles(60), ENGINE).items()}
    # 60 rows of a flat price: out are #5, #7 (61 rows), #9, #11, #17 (250), #24 (70 rows), and two that a flat
    # price cannot compute: #13 (nothing moved) and #15 (high == low)
    assert [id_ for id_, ok in available.items() if not ok] == [5, 7, 9, 11, 13, 15, 17, 24]
    # #10 needs 55 rows (a TA-Lib value exists earlier), #8 needs 45: both are in at 60
    assert available[8] and available[10]


def test_warm_up_minimums_beat_a_value_that_exists_earlier() -> None:
    """RSI has a value at 15 rows, but #8 needs 45: it must stay unavailable."""
    raw = scoring.raw_values(candles(30), ENGINE)
    assert raw[8] is None
    assert raw[1] is not None  # SMA20 is fine with 30 rows


def test_percentile_ranks_use_only_symbols_that_have_the_value() -> None:
    raw = {
        "LOW": {6: 0.1, 7: None, 20: 0.05},
        "MID": {6: 0.2, 7: 0.3, 20: 0.02},
        "TOP": {6: 0.3, 7: None, 20: 0.01},
    }
    full = {indicator.id: None for indicator in INDICATORS}
    ranks = scoring.percentile_ranks({symbol: {**full, **values} for symbol, values in raw.items()})
    assert ranks["LOW"][6] == 0.0 and ranks["MID"][6] == 0.5 and ranks["TOP"][6] == 1.0
    assert ranks["MID"][7] == 0.5 and 7 not in ranks["LOW"]  # alone among the symbols that have #7
    assert ranks["TOP"][20] == 0.0  # volatility is ranked high-to-low here; scoring flips it


def test_score_indicators() -> None:
    raw: dict[int, float | None] = {indicator.id: None for indicator in INDICATORS}
    raw.update({1: 0.015, 3: 1.0, 6: 0.2, 19: 0.13, 20: 0.02})  # #1 half, #3 yes, #6 and #20 ranked, #19 half
    results = {result.id: result for result in scoring.score_indicators(raw, {6: 0.8, 20: 0.25})}
    assert results[1].points == pytest.approx(1.5)
    assert results[1].raw == {"close_vs_sma20": 0.015}
    assert results[3].points == 4
    assert results[6].points == pytest.approx(4.0)  # 5 x 0.8, higher is better
    assert results[6].raw == {"return_20": 0.2, "percentile": 0.8}
    assert results[20].points == pytest.approx(2.25)  # 3 x (1 - 0.25): lower volatility is better
    assert results[19].points == pytest.approx(2.0)
    assert results[2].status == IndicatorStatus.UNAVAILABLE
    assert results[2].points == 0 and results[2].raw == {}
    assert len(results) == 24


def test_the_engine_is_injected_not_imported() -> None:
    """Swapping the library is passing another `Indicators`: RSI #8 and the SMA gap #1 follow the engine given."""
    flat = candles(60)
    engine_a = scoring.raw_values(flat, StubIndicators(50.0))
    assert engine_a[8] == 50.0  # rsi
    assert engine_a[1] == pytest.approx(100 / 50 - 1)  # close 100 over an "SMA" of 50
    assert engine_a[6] == 0.0  # a candles-only feature does not use the engine
    assert scoring.raw_values(flat, ENGINE)[1] == 0.0  # the real engine on the same candles: a flat price, no gap


def full_raw(**raw: float | Detection | None) -> dict[int, float | Detection | None]:
    """Every indicator unavailable except the ones given as `r4=...`."""
    base: dict[int, float | Detection | None] = {indicator.id: None for indicator in INDICATORS}
    base.update({int(name[1:]): value for name, value in raw.items()})
    return base


def by_id(raw: dict[int, float | Detection | None]) -> dict[int, IndicatorResult]:
    return {result.id: result for result in scoring.score_indicators(raw, {})}


def test_reversal_indicators_count_only_while_sma50_is_not_falling() -> None:
    found = Detection(0.5, {"pattern": "engulfing"})
    open_gate = by_id(full_raw(r4=0.01, r22=found, r23=found))
    assert open_gate[22].status == IndicatorStatus.SCORED
    assert open_gate[22].points == pytest.approx(2.5)  # 5 x 0.5
    assert open_gate[22].raw == {"rsi_divergence": 0.5, "pattern": "engulfing"}  # the facts travel with the points

    closed = by_id(full_raw(r4=-0.01, r22=found, r23=found))
    assert closed[22].status == closed[23].status == IndicatorStatus.GATE_CLOSED
    assert closed[22].points == 0 and closed[22].raw == {"sma50_change": -0.01}

    unknown = by_id(full_raw(r22=found, r23=found))  # #4 could not be computed: the gate cannot be judged
    assert unknown[22].status == unknown[23].status == IndicatorStatus.UNAVAILABLE


def test_gate_does_not_touch_the_trendline_and_an_unavailable_reversal_stays_unavailable() -> None:
    results = by_id(full_raw(r4=-0.01, r24=Detection(1.0, {"touches": 3}), r22=None))
    assert results[24].status == IndicatorStatus.SCORED and results[24].points == 4  # #24 is not gated
    assert results[24].raw == {"trendline_breakout": 1.0, "touches": 3}
    assert results[22].status == IndicatorStatus.UNAVAILABLE  # too few rows beats a closed gate
