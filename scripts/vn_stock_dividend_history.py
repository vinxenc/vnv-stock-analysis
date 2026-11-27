"""Re-store the whole price history of the symbols whose ex-rights date (GDKHQ) falls in the sessions due.

The sources quote their history adjusted as of the day of the fetch, while `vn_stock_prices` keeps each bar as it was
stored: on an ex-rights date every older stored bar of the symbol is raw and the history has a fake step. This job runs
before the price retrieval, on the sessions due (`$SESSIONS`, `first..last`, see vn_stock_price_sync_session; default
today). It asks VNDirect (2 retries) which symbols of `data/hose_symbols.csv` have an ex-rights date (a cash or stock
dividend, bonus shares, a rights issue) on a working day from the first session to today: a day after the last session
counts too, because the sources adjust the history from midnight on its eve, so the bars the retrieval fetches already
carry it. It fetches each one's daily bars from START (2019-01-01) to the last session, one request per year (DNSE,
else VNDirect for every year, 1 retry each, `delay` seconds between requests), and in one transaction per symbol upserts
them and deletes its stored rows the source no longer has between the first and last bar of each year it returned (a
row stored from another source, or a bar the source drops as invalid, would keep its raw price). The stored history of
those symbols is then the source's own.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_dividend_history [symbols_csv]
Default: data/hose_symbols.csv
Exit 0 = done (also when no symbol has an ex-rights date in the span), anything else = crash (a symbol no source
could fetch, or VNDirect not answering): the price retrieval waits for this job.
"""

import datetime as dt
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy import Engine, delete, or_
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed

from libs.constants import VN_TZ
from libs.db import connect
from libs.db.models import Price
from libs.logger import Logger, LogxideLogger
from libs.prices import DNSE, PriceNotFoundError, PriceSource, VNDirect
from scripts.vn_holiday import working_days
from scripts.vn_stock_daily_price_store import upsert
from scripts.vn_stock_latest_price_retrieval import read_symbols
from scripts.vn_stock_price_sync_session import from_env

START = dt.date(2019, 1, 1)
# Not VPS: its bars before mid-2021 ignore the older corporate actions (HPG 2019-01-02: 9.92, DNSE 7.30, VNDirect
# 7.293; checked 2026-11-27, FPT and HPG differ by over 2% up to 2021-05-31). DNSE and VNDirect agree within 2%.
SOURCES = (DNSE(), VNDirect())
CALENDAR = VNDirect()
logger = LogxideLogger("vn_stock_dividend_history")


@retry(
    stop=stop_after_attempt(2), wait=wait_fixed(1), retry=retry_if_not_exception_type(PriceNotFoundError), reraise=True
)
def fetch(source: PriceSource, symbol: str, start: dt.date, end: dt.date) -> list[Price]:
    return source.get_history(symbol, start, end)


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def ex_rights(calendar: VNDirect, day: dt.date) -> set[str]:
    """One VNDirect request, 2 retries: the whole sync waits for it."""
    return calendar.get_ex_rights(day)


def history(symbol: str, last: dt.date, sources: Sequence[PriceSource], pause: Callable[[], None]) -> list[list[Price]]:
    """Every bar from START to `last`, one list per year (empty before the listing), from the first source that answers
    every year: one source for the whole history, so it is adjusted one way."""
    errors = []
    for source in sources:
        try:
            years = []
            for year in range(START.year, last.year + 1):
                pause()
                years.append(fetch(source, symbol, dt.date(year, 1, 1), min(last, dt.date(year, 12, 31))))
        except Exception as error:
            errors.append(f"{source.name}: {type(error).__name__}: {error}")
            continue
        if any(years):
            return years
        errors.append(f"{source.name}: no bar since {START}")
    raise RuntimeError(f"{symbol}: all sources failed: " + "; ".join(errors))


def restore(symbol: str, years: list[list[Price]], engine: Engine, log: Logger) -> None:
    """Upsert the bars, and delete the symbol's stored rows the source no longer has within the span of each year it
    returned (never in a year it returned nothing for), in one transaction.

    The boundary is the first and last bar returned, never the span asked: a stored row past the last bar of a year is
    kept, since a source that lags on a session must not delete a valid bar that no later run would fetch again. The
    sessions due are the exception that needs no delete: the retrieval right after this job fetches them again for
    every symbol, through every source."""
    bars = [bar for year in years for bar in year]
    spans = [Price.date.between(year[0].date, year[-1].date) for year in years if year]
    stale = delete(Price).where(Price.symbol == symbol, or_(*spans), Price.date.not_in([bar.date for bar in bars]))
    with engine.begin() as connection:
        deleted = connection.execute(stale).rowcount
        upsert(connection, bars)
    log.info("%s: %d bars re-stored from %s (%s), %d stale rows deleted", symbol, len(bars), bars[0].date,
             bars[-1].source, deleted)  # fmt: skip


def main(
    symbols_csv: Path = Path("data/hose_symbols.csv"),
    engine: Engine | None = None,
    sessions: tuple[dt.date, dt.date] | None = None,
    sources: Sequence[PriceSource] = SOURCES,
    calendar: VNDirect = CALENDAR,
    delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    log: Logger = logger,
    today: dt.date | None = None,
) -> int:
    first, last = sessions or from_env()
    end = max(last, today or dt.datetime.now(VN_TZ).date())
    hose = set(read_symbols(symbols_csv))
    symbols = sorted(set().union(*(ex_rights(calendar, day) for day in working_days(first, end))) & hose)
    log.info("%d symbols with an ex-rights date from %s to %s: %s", len(symbols), first, end, " ".join(symbols))
    if not symbols:
        return 0
    engine = engine or connect()
    for symbol in symbols:
        restore(symbol, history(symbol, last, sources, lambda: sleep(delay)), engine, log)
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
