"""Re-store the whole price history of the symbols whose ex-rights date (GDKHQ) is the session due.

The sources quote their history adjusted as of the day of the fetch, while `vn_stock_prices` keeps each bar as it was
stored: on an ex-rights date every older stored bar of the symbol is raw and the history has a fake step. This job runs
before the price retrieval, on the session due (`$SESSION`, see vn_stock_price_sync_session; default today). It asks
VNDirect which symbols of `data/hose_symbols.csv` have an ex-rights date on the session (a cash or stock dividend,
bonus shares, a rights issue), fetches each one's daily bars from START (2019-01-01) to the session, one request per
year (DNSE, else VPS for every year, 1 retry each, `delay` seconds between requests), and upserts them, one transaction
per symbol. The stored history of those symbols is then the source's own. Each run checks its own session, so a
delayed or missed run is caught up session by session, like the prices.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_dividend_history [symbols_csv]
Default: data/hose_symbols.csv
Exit 0 = done (also when no symbol has an ex-rights date on the session), anything else = crash (a symbol no source
could fetch, or VNDirect not answering): the price retrieval waits for this job.
"""

import datetime as dt
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy import Engine
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed

from libs.db import connect
from libs.logger import Logger, LogxideLogger
from libs.prices import DNSE, VPS, Price, PriceNotFoundError, PriceSource, VNDirect
from scripts.vn_stock_daily_price_store import store
from scripts.vn_stock_latest_price_retrieval import read_symbols
from scripts.vn_stock_price_sync_session import from_env

START = dt.date(2019, 1, 1)
SOURCES = (DNSE(), VPS())
CALENDAR = VNDirect()
logger = LogxideLogger("vn_stock_dividend_history")


@retry(
    stop=stop_after_attempt(2), wait=wait_fixed(1), retry=retry_if_not_exception_type(PriceNotFoundError), reraise=True
)
def fetch(source: PriceSource, symbol: str, start: dt.date, end: dt.date) -> list[Price]:
    return source.get_history(symbol, start, end)


def history(symbol: str, session: dt.date, sources: Sequence[PriceSource], pause: Callable[[], None]) -> list[Price]:
    """Every bar from START to the session from the first source that answers every year: one source for the whole
    history, so it is adjusted one way."""
    errors = []
    for source in sources:
        try:
            bars = []
            for year in range(START.year, session.year + 1):
                pause()
                bars += fetch(source, symbol, dt.date(year, 1, 1), min(session, dt.date(year, 12, 31)))
        except Exception as error:
            errors.append(f"{source.name}: {type(error).__name__}: {error}")
            continue
        if bars:
            return bars
        errors.append(f"{source.name}: no bar since {START}")
    raise RuntimeError(f"{symbol}: all sources failed: " + "; ".join(errors))


def main(
    symbols_csv: Path = Path("data/hose_symbols.csv"),
    engine: Engine | None = None,
    session: dt.date | None = None,
    sources: Sequence[PriceSource] = SOURCES,
    calendar: VNDirect = CALENDAR,
    delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    log: Logger = logger,
) -> int:
    session = session or from_env()
    symbols = sorted(calendar.get_ex_rights(session) & set(read_symbols(symbols_csv)))
    log.info("%d symbols with an ex-rights date on %s: %s", len(symbols), session, " ".join(symbols))
    if not symbols:
        return 0
    engine = engine or connect()
    for symbol in symbols:
        bars = history(symbol, session, sources, lambda: sleep(delay))
        store(bars, engine)
        log.info("%s: %d bars re-stored from %s (%s)", symbol, len(bars), bars[0].date, bars[-1].source)
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
