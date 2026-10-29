"""Is today (Vietnam time) a weekend or a Vietnamese public holiday?

Usage: uv run python -m scripts.vn_holiday [--previous] [YYYY-MM-DD]   (default: today in UTC+7)
Exit 0 = day off (weekend/holiday), 3 = working day, anything else = the check itself failed.
--previous: instead print (stdout, YYYY-MM-DD) the last trading day before that day, and exit 0.
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


def previous_trading_day(day: date) -> date:
    """The most recent day before `day` that is not a weekend or public holiday."""
    day -= timedelta(days=1)
    while off_reason(day):
        day -= timedelta(days=1)
    return day


if __name__ == "__main__":
    args = [arg for arg in sys.argv[1:] if arg != "--previous"]
    day = date.fromisoformat(args[0]) if args else datetime.now(VN_TZ).date()
    if "--previous" in sys.argv:
        sys.stdout.write(f"{previous_trading_day(day)}\n")  # stdout is the data; the logger writes to stderr
        sys.exit(0)
    reason = off_reason(day)
    logger.info("%s %s: %s", day, f"{day:%a}", f"day off ({reason})" if reason else "working day")
    sys.exit(0 if reason else WORKING_DAY)
