"""Find the sessions the price sync is due to fetch: from the first working day (weekends and public holidays skipped)
after the newest row of `vn_stock_price_sync_history` to the newest session HOSE has closed (CLOSE, Vietnam time), not
the wall-clock day, so a cron run that GitHub delays past midnight (Vietnam time) still fetches the right session, and
a run after a failed or missed one catches every session up at once. An empty history fetches the newest closed
session.

The workflow passes the span to the next jobs (`SESSIONS`, `first..last`): the dividend history and the retrieval;
the store records every session it stored in the history with the prices. A run that fails before the store
leaves the sessions due. The span is fixed here, never in a later job: a job delayed past the next close must not take
a session that is still trading.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_price_sync_session
Exit 0, with `sessions=YYYY-MM-DD..YYYY-MM-DD` written to `$GITHUB_OUTPUT` (when set) if sessions are due, nothing if
nothing new has closed since the newest stored session; anything else = crash.
"""

import datetime as dt
import os
import sys

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from libs.constants import VN_TZ
from libs.db import connect
from libs.db.models import PriceSyncHistory
from libs.logger import Logger, LogxideLogger
from scripts.vn_holiday import next_session, off_reason

CLOSE = dt.time(14, 45)  # the end of HOSE's closing auction
logger = LogxideLogger("vn_stock_price_sync_session")


def from_env() -> tuple[dt.date, dt.date]:
    """The sessions the next jobs work on, first and last: `$SESSIONS` (`first..last` or one ISO date, set by the
    workflow), else today in Vietnam time."""
    value = os.environ.get("SESSIONS")
    if not value:
        today = dt.datetime.now(VN_TZ).date()
        return today, today
    first, _, last = value.partition("..")
    return dt.date.fromisoformat(first), dt.date.fromisoformat(last or first)


def newest_closed(now: dt.datetime) -> dt.date:
    """The newest working day whose session has closed at `now` (Vietnam time)."""
    day = now.date() if now.time() >= CLOSE else now.date() - dt.timedelta(days=1)
    while off_reason(day):
        day -= dt.timedelta(days=1)
    return day


def due_sessions(engine: Engine, now: dt.datetime) -> tuple[dt.date, dt.date] | None:
    """The first and last session to fetch at `now` (Vietnam time), or None when nothing new has closed."""
    with Session(engine) as session:
        stored = session.exec(select(func.max(PriceSyncHistory.date))).one()
    last = newest_closed(now)
    first = next_session(stored) if stored else last
    return (first, last) if first <= last else None


def main(engine: Engine | None = None, now: dt.datetime | None = None, log: Logger = logger) -> int:
    now = now or dt.datetime.now(VN_TZ)
    due = due_sessions(engine or connect(), now)
    if due is None:
        log.warning("no session due at %s: nothing has closed since the newest stored one", f"{now:%Y-%m-%d %H:%M}")
        return 0
    first, last = due
    log.info("sessions due: %s to %s", first, last)
    if output := os.environ.get("GITHUB_OUTPUT"):  # the next jobs read it as `needs.<job>.outputs.sessions`
        with open(output, "a", encoding="utf-8") as file:
            file.write(f"sessions={first.isoformat()}..{last.isoformat()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
