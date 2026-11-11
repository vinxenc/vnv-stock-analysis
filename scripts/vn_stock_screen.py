"""Drop the illiquid symbols: write the codes whose average turnover over their last 20 sessions up to the session
screened is at least 20 billion VND per session.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_screen [output_csv]
Default: out/liquid_symbols.csv (a `code` column, same shape as data/hose_symbols.csv)
The session screened is the first working day (weekends and public holidays skipped) after the newest row of
`vn_stock_screen_history`, not the wall-clock day: a cron run that GitHub delays past midnight (Vietnam time) still
screens the right session. When that session is after today there is nothing to do yet. An empty history screens today.
The session screened goes to `screen_session.txt` next to the CSV; the history only gets it from `vn_stock_screen_done`,
the last job of the workflow, so a run that fails after the screen leaves the session due and the next run redoes it.
Fails (crash, exit 1) unless the session screened has bars in `vn_stock_prices`: the sync has not finished or failed,
and old data must not be reported as fresh. Also fails when fewer than MIN_COVERAGE of the previous session's symbols
have a bar on it: a partial sync would silently shrink the shortlist.
Exit 0 = shortlist and session written, 4 = nobody is liquid enough (nothing written), 5 = nothing to screen yet
(nothing written), anything else = crash.
"""

import csv
import datetime as dt
import sys
from pathlib import Path

from sqlalchemy import Engine, case, func
from sqlmodel import Session, select

from libs.constants import MIN_COVERAGE, NO_DATA, NOT_DUE, VN_TZ
from libs.db import connect
from libs.db.models import Price, ScreenHistory
from libs.logger import Logger, LogxideLogger
from scripts.vn_holiday import off_reason

MIN_TURNOVER = 20_000_000  # thousand VND (prices are in thousand VND) = 20 billion VND per session
SESSION_FILE = "screen_session.txt"  # the ISO date screened, next to the shortlist
SESSIONS = 20  # rows, not calendar days (holidays); a symbol with fewer rows is averaged over the rows it has
logger = LogxideLogger("vn_stock_screen")


def next_session(last: dt.date) -> dt.date:
    """The first working day after `last`: weekends and Vietnamese public holidays are skipped."""
    day = last + dt.timedelta(days=1)
    while off_reason(day):
        day += dt.timedelta(days=1)
    return day


def screen(engine: Engine, today: dt.date, log: Logger = logger) -> list[str]:
    """Symbols that traded on `today` and whose average `close × volume` over their last SESSIONS rows up to it is >=
    MIN_TURNOVER. `today` is the session screened, which may be before the real today (see the module docstring).

    Sorted. A symbol with no row today, or a halted one (volume 0 today), is dropped whatever its average. A halted
    earlier day counts as 0 turnover. A symbol with fewer than SESSIONS rows is averaged over the rows it has.
    ponytail: until `vn_stock_prices` is backfilled a new listing can pass on a single big day; require SESSIONS rows
    then.
    """
    recent = (
        select(
            Price.symbol,
            Price.date,
            (Price.close * Price.volume).label("turnover"),
            func.row_number().over(partition_by=Price.symbol, order_by=Price.date.desc()).label("rank"),
        )
        .where(Price.date <= today)
        .subquery()
    )
    with Session(engine) as session:
        newest = (
            session.exec(  # the last two sessions up to `today` with their number of bars (later ones are not ours)
                select(Price.date, func.count())
                .where(Price.date <= today)
                .group_by(Price.date)
                .order_by(Price.date.desc())
                .limit(2)
            ).all()
        )
        latest = newest[0][0] if newest else None
        if latest != today:
            raise RuntimeError(f"no bar on {today} (newest session up to it: {latest}): the sync is late or failed")
        if len(newest) > 1:  # none on the very first day
            previous, before = newest[1]
            both = session.exec(  # symbols with a bar on both days: a new listing cannot make up for a missing symbol
                select(func.count()).select_from(
                    select(Price.symbol)
                    .where(Price.date.in_([today, previous]))
                    .group_by(Price.symbol)
                    .having(func.count() == 2)
                    .subquery()
                )
            ).one()
            if both < MIN_COVERAGE * before:
                raise RuntimeError(
                    f"{both} of the {before} symbols of {previous} have a bar on {today}: the sync is incomplete"
                )
        rows = session.exec(
            select(recent.c.symbol, func.avg(recent.c.turnover))
            .where(recent.c.rank <= SESSIONS)
            .group_by(recent.c.symbol)
            .having(func.max(case((recent.c.date == today, recent.c.turnover), else_=0)) > 0)  # traded today
        ).all()
    liquid = sorted(symbol for symbol, average in rows if average >= MIN_TURNOVER)
    log.info("%s: kept %d of %d symbols, dropped %d", today, len(liquid), len(rows), len(rows) - len(liquid))
    return liquid


def main(
    output_csv: Path = Path("out/liquid_symbols.csv"),
    engine: Engine | None = None,
    today: dt.date | None = None,
    log: Logger = logger,
) -> int:
    session_file = output_csv.with_name(SESSION_FILE)
    output_csv.unlink(missing_ok=True)  # an older shortlist must not pass for today's, whatever happens next
    session_file.unlink(missing_ok=True)
    engine = engine or connect()
    today = today or dt.datetime.now(VN_TZ).date()
    with Session(engine) as session:
        last = session.exec(select(func.max(ScreenHistory.date))).one()
    day = next_session(last) if last else today  # an empty history (a fresh database): screen today
    if day > today:
        log.info("%s is screened, the next session %s is after today %s: nothing to screen yet", last, day, today)
        return NOT_DUE
    liquid = screen(engine, day, log)
    if not liquid:
        log.error("no symbol reaches the turnover threshold, nothing written")
        return NO_DATA
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["code"])
        writer.writerows([code] for code in liquid)
    session_file.write_text(day.isoformat(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
