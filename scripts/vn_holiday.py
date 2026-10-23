"""Is today (Vietnam time) a weekend or a Vietnamese public holiday?

Usage: uv run python scripts/vn_holiday.py [YYYY-MM-DD]   (default: today in UTC+7)
Exit 0 = day off (weekend/holiday), 1 = working day,
so `if uv run python scripts/vn_holiday.py; then ...` reads as "if holiday".
Holidays come from the `holidays` package: Tết, Giỗ Tổ (lunar), nghỉ bù, and government-decreed swap days.
"""
import sys
from datetime import date, datetime, timedelta, timezone

import holidays

VN_TZ = timezone(timedelta(hours=7))


def off_reason(d: date) -> str | None:
    """Why `d` is a day off in Vietnam, or None for a working day."""
    if d.weekday() >= 5:
        return "weekend"
    return holidays.VN(years=d.year).get(d)


if __name__ == "__main__":
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(VN_TZ).date()
    reason = off_reason(d)
    print(f"{d} {d:%a}: " + (f"day off ({reason})" if reason else "working day"))
    sys.exit(0 if reason else 1)
