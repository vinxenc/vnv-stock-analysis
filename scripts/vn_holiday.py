"""Is today (Vietnam time) a weekend or a Vietnamese public holiday?

Usage: uv run python -m scripts.vn_holiday [YYYY-MM-DD]   (default: today in UTC+7)
Exit 0 = day off (weekend/holiday), 3 = working day, anything else = the check itself failed.
Holidays come from the `holidays` package: Tết, Giỗ Tổ (lunar), nghỉ bù, and government-decreed swap days.
"""
import sys
from datetime import date, datetime, timedelta, timezone

import holidays

from libs.logger import LogxideLogger

VN_TZ = timezone(timedelta(hours=7))
logger = LogxideLogger("vn_holiday")
WORKING_DAY = 3  # not 1: Python exits 1 on an uncaught error, which must not read as "working day"


def off_reason(day: date) -> str | None:
    """Why `day` is a day off in Vietnam, or None for a working day."""
    if day.weekday() >= 5:
        return "weekend"
    return holidays.VN(years=day.year).get(day)


if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(VN_TZ).date()
    reason = off_reason(day)
    logger.info("%s %s: %s", day, f"{day:%a}", f"day off ({reason})" if reason else "working day")
    sys.exit(0 if reason else WORKING_DAY)
