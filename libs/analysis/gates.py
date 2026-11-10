"""Gates and flags. A gate decides what counts, a flag is only shown; neither repairs or re-checks the data.

The stored history is taken as correct, so there is no corporate-action or missing-session check here.
"""

import datetime as dt

from libs.analysis.models import Flag, IndicatorResult, IndicatorStatus

MIN_AVAILABLE_POINTS = 80  # a symbol is scored only when the indicators it could compute are worth at least this
LOW_COVERAGE_POINTS = 90  # below this the score rests on few indicators: show the flag
CEILING = 0.07  # HOSE daily price limit
CEILING_TOLERANCE = 0.005  # "locked" = the close is within 0.5% of the ceiling
NEW_LISTING_DAYS = 90  # calendar days, about 60 sessions: where the score first becomes available


def available_points(indicators: list[IndicatorResult]) -> float:
    """Points the symbol could have earned: the maximums of every indicator that was not `unavailable`."""
    return sum(item.max_points for item in indicators if item.status != IndicatorStatus.UNAVAILABLE)


def is_scored(available: float) -> bool:
    """Coverage gate: below MIN_AVAILABLE_POINTS there is no score, so a few cheap indicators cannot reach 100."""
    return available >= MIN_AVAILABLE_POINTS


def uptrend_gate(sma50_change: float | None) -> IndicatorStatus | None:
    """Gate of the reversal indicators (#22, #23): they count only inside an uptrend, i.e. SMA50 not falling (#4).

    None = open, score the indicator. GATE_CLOSED = SMA50 is falling: 0 points, still available.
    UNAVAILABLE = #4 could not be computed (too few rows), so the gate cannot be judged.
    """
    if sma50_change is None:
        return IndicatorStatus.UNAVAILABLE
    return IndicatorStatus.GATE_CLOSED if sma50_change < 0 else None


def flags(close: float, previous_close: float, listed_date: dt.date, as_of: dt.date, available: float) -> list[Flag]:
    """Flags shown next to the score; they never change it."""
    result: list[Flag] = []
    if close >= previous_close * (1 + CEILING) * (1 - CEILING_TOLERANCE):
        result.append(Flag.CEILING_LOCKED)
    if (as_of - listed_date).days < NEW_LISTING_DAYS:
        result.append(Flag.NEW_LISTING)
    if available < LOW_COVERAGE_POINTS:
        result.append(Flag.LOW_COVERAGE)
    return result
