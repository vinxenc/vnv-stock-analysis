"""Find the session the price sync is due to fetch: the first working day (weekends and public holidays skipped) after
the newest row of `vn_stock_price_sync_history`, not the wall-clock day, so a cron run that GitHub delays past
midnight (Vietnam time) still fetches the right session. An empty history fetches today. The session is due once
HOSE has closed on it (CLOSE, Vietnam time); a later session waits.

The workflow passes it to the next jobs (`SESSION`): the dividend history, the retrieval and the store,
which records it in the history with the prices. A run that fails before the store leaves the session due.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_price_sync_session
Exit 0 = a session due (logged, and written as `session=YYYY-MM-DD` to `$GITHUB_OUTPUT` when set),
5 = nothing due yet (a day off, or the session already stored), anything else = crash.
"""

import datetime as dt
import os
import sys

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from libs.constants import NOT_DUE, VN_TZ
from libs.db import connect
from libs.db.models import PriceSyncHistory
from libs.logger import Logger, LogxideLogger
from scripts.vn_holiday import next_session

CLOSE = dt.time(14, 45)  # the end of HOSE's closing auction
logger = LogxideLogger("vn_stock_price_sync_session")


def from_env() -> dt.date:
    """The session the next jobs work on: `$SESSION` (ISO date, set by the workflow), else today in Vietnam time."""
    value = os.environ.get("SESSION")
    return dt.date.fromisoformat(value) if value else dt.datetime.now(VN_TZ).date()


def due_session(engine: Engine, now: dt.datetime) -> dt.date | None:
    """The session to fetch at `now` (Vietnam time), or None when it has not closed yet."""
    with Session(engine) as session:
        last = session.exec(select(func.max(PriceSyncHistory.date))).one()
    day = next_session(last) if last else now.date()
    return day if (day, CLOSE) <= (now.date(), now.time()) else None


def main(engine: Engine | None = None, now: dt.datetime | None = None, log: Logger = logger) -> int:
    now = now or dt.datetime.now(VN_TZ)
    day = due_session(engine or connect(), now)
    if day is None:
        log.warning("no session due at %s: a day off, or the next session has not closed yet", f"{now:%Y-%m-%d %H:%M}")
        return NOT_DUE
    log.info("session due: %s", day)
    if output := os.environ.get("GITHUB_OUTPUT"):  # the next jobs read it as `needs.<job>.outputs.session`
        with open(output, "a", encoding="utf-8") as file:
            file.write(f"session={day.isoformat()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
