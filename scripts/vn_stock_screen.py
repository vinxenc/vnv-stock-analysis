"""Drop the illiquid symbols: write the codes whose average turnover over their last 20 sessions up to today is at
least 20 billion VND per session (today = Vietnam time).

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_screen [output_csv]
Default: out/liquid_symbols.csv (a `code` column, same shape as data/hose_symbols.csv)
Fails (crash, exit 1) unless the newest session in `prices` is today: the sync has not finished or failed, and old data
must not be reported as fresh.
Exit 0 = shortlist written, 4 = nobody is liquid enough (nothing written), anything else = crash.
"""
import csv
import datetime as dt
import sys
from pathlib import Path

from sqlalchemy import Engine, case, func
from sqlmodel import Session, select

from libs.db import connect
from libs.db.models import Price
from libs.logger import Logger, LogxideLogger
from scripts.vn_holiday import VN_TZ

NO_DATA = 4  # same meaning as in the other scripts; the workflow does not map it, any non-zero fails the job
MIN_TURNOVER = 20_000_000  # thousand VND (prices are in thousand VND) = 20 billion VND per session
SESSIONS = 20  # rows, not calendar days (holidays); a symbol with fewer rows is averaged over the rows it has
logger = LogxideLogger("vn_stock_screen")


def screen(engine: Engine, today: dt.date, log: Logger = logger) -> list[str]:
    """Symbols that traded today and whose average `close × volume` over their last SESSIONS rows is >= MIN_TURNOVER.

    Sorted. A symbol with no row today, or a halted one (volume 0 today), is dropped whatever its average. A halted
    earlier day counts as 0 turnover. A symbol with fewer than SESSIONS rows is averaged over the rows it has.
    ponytail: until `prices` is backfilled a new listing can pass on a single big day; require SESSIONS rows then.
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
        latest = session.exec(select(func.max(Price.date))).one()
        if latest != today:
            raise RuntimeError(f"newest session in prices is {latest}, expected {today}: the sync is late or failed")
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
    liquid = screen(engine or connect(), today or dt.datetime.now(VN_TZ).date(), log)
    if not liquid:
        log.error("no symbol reaches the turnover threshold, nothing written")
        output_csv.unlink(missing_ok=True)  # an older shortlist must not pass for today's
        return NO_DATA
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["code"])
        writer.writerows([code] for code in liquid)
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
