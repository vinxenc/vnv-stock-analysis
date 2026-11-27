"""The Vietnamese market calendar: weekends, public holidays and the closures the `holidays` package misses.

Holidays come from the `holidays` package: Tết, Giỗ Tổ (lunar), nghỉ bù, and government-decreed swap days.
"""

from datetime import date, timedelta

import holidays

# Market closures the `holidays` package does not list. Checked against every weekday of `vn_stock_prices` from
# 2025-01-02 to 2026-11-09: 2026-01-02 is the only weekday without a session that the package calls a working day.
CLOSURES = {date(2026, 1, 2): "New Year bridge day"}


def off_reason(day: date) -> str | None:
    """Why `day` is a day off in Vietnam, or None for a working day."""
    if day.weekday() >= 5:
        return "weekend"
    return CLOSURES.get(day) or holidays.VN(years=day.year).get(day)


def next_session(last: date) -> date:
    """The first working day after `last`: weekends and Vietnamese public holidays are skipped."""
    day = last + timedelta(days=1)
    while off_reason(day):
        day += timedelta(days=1)
    return day


def working_days(first: date, last: date) -> list[date]:
    """Every working day from `first` to `last`, both included."""
    days = (first + timedelta(days=offset) for offset in range((last - first).days + 1))
    return [day for day in days if not off_reason(day)]
