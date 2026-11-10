import datetime as dt

import pytest

from libs.analysis.gates import available_points, flags, is_scored, uptrend_gate
from libs.analysis.models import Flag, IndicatorResult, IndicatorStatus, Theme

AS_OF = dt.date(2026, 11, 10)
OLD = dt.date(2016, 11, 25)


def indicator(status: IndicatorStatus, max_points: float, points: float = 0) -> IndicatorResult:
    return IndicatorResult(id=1, theme=Theme.TREND, status=status, points=points, max_points=max_points)


def test_available_points_count_scored_and_gate_closed_but_not_unavailable() -> None:
    indicators = [
        indicator(IndicatorStatus.SCORED, 5, 3),  # the points earned do not matter, the maximum does
        indicator(IndicatorStatus.GATE_CLOSED, 4),
        indicator(IndicatorStatus.UNAVAILABLE, 6),
    ]
    assert available_points(indicators) == 9
    assert available_points([]) == 0


@pytest.mark.parametrize(("available", "scored"), [(79.9, False), (80, True), (100, True)])
def test_coverage_gate_edge(available: float, scored: bool) -> None:
    assert is_scored(available) is scored


@pytest.mark.parametrize(
    ("sma50_change", "gate"),
    [
        (0.02, None),
        (0.0, None),  # not falling is enough
        (-0.001, IndicatorStatus.GATE_CLOSED),
        (None, IndicatorStatus.UNAVAILABLE),
    ],
)
def test_uptrend_gate(sma50_change: float | None, gate: IndicatorStatus | None) -> None:
    assert uptrend_gate(sma50_change) == gate


@pytest.mark.parametrize(
    ("close", "locked"),
    [(107.0, True), (106.5, True), (106.4, False), (100.0, False), (110.0, True)],  # ceiling 107, 0.5% below = 106.465
)
def test_ceiling_locked(close: float, locked: bool) -> None:
    assert (Flag.CEILING_LOCKED in flags(close, 100.0, OLD, AS_OF, 100)) is locked


@pytest.mark.parametrize(
    ("listed_date", "new"),
    [(AS_OF, True), (AS_OF - dt.timedelta(days=89), True), (AS_OF - dt.timedelta(days=90), False), (OLD, False)],
)
def test_new_listing(listed_date: dt.date, new: bool) -> None:
    assert (Flag.NEW_LISTING in flags(100, 100, listed_date, AS_OF, 100)) is new


@pytest.mark.parametrize(("available", "low"), [(89.9, True), (90, False), (100, False)])
def test_low_coverage(available: float, low: bool) -> None:
    assert (Flag.LOW_COVERAGE in flags(100, 100, OLD, AS_OF, available)) is low


def test_no_flag_for_an_ordinary_symbol() -> None:
    assert flags(101, 100, OLD, AS_OF, 100) == []
