"""Is today (Vietnam time) a weekend or a Vietnamese public holiday?

Usage: uv run python -m scripts.vn_holiday [YYYY-MM-DD]   (default: today in UTC+7)
Exit 0 = day off (weekend/holiday), 3 = working day, anything else = the check itself failed.
Holidays come from the `holidays` package: Tết, Giỗ Tổ (lunar), nghỉ bù, and government-decreed swap days.
"""

import sys
from datetime import date, datetime, timedelta

import holidays

from libs.constants import VN_TZ
from libs.logger import LogxideLogger

logger = LogxideLogger("vn_holiday")
WORKING_DAY = 3  # not 1: Python exits 1 on an uncaught error, which must not read as "working day"
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


if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(VN_TZ).date()
    reason = off_reason(day)
    logger.info("%s %s: %s", day, f"{day:%a}", f"day off ({reason})" if reason else "working day")
    sys.exit(0 if reason else WORKING_DAY)
