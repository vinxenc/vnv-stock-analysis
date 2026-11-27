"""Fetch the daily bar of the session due (`$SESSION`, see vn_stock_price_sync_session; default today) of every symbol
in a CSV and write them as one JSON array.

Usage: uv run python -m scripts.vn_stock_latest_price_retrieval [symbols_csv] [output_json]
Defaults: data/hose_symbols.csv  out/vn_stock_latest_prices.json
Sources per symbol: DNSE -> VPS -> VNDirect, 1 retry each (tenacity). A symbol that fails everywhere is skipped.
Exit 0 = prices written, 4 = no price at all or fewer than MIN_COVERAGE of the symbols (no file written), anything
else = crash.
"""

import csv
import datetime as dt
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed

from libs.constants import MIN_COVERAGE, NO_DATA
from libs.logger import Logger, LogxideLogger
from libs.prices import DNSE, VPS, Price, PriceNotFoundError, PriceSource, VNDirect
from libs.prices.base import validate_symbol
from scripts.vn_stock_price_sync_session import from_env

SOURCES = (DNSE(), VPS(), VNDirect())
logger = LogxideLogger("vn_stock_latest_price_retrieval")


def read_symbols(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(dict.fromkeys(validate_symbol(row["code"]) for row in csv.DictReader(file)))  # dedupe, keep order


@retry(
    stop=stop_after_attempt(2), wait=wait_fixed(1), retry=retry_if_not_exception_type(PriceNotFoundError), reraise=True
)
def fetch(source: PriceSource, symbol: str, session: dt.date) -> Price:
    """One source, 1 retry after a failure; an unknown ticker, or no bar on the session (halted, not published yet),
    will not appear on a second try, so no retry then."""
    bars = source.get_history(symbol, session, session)
    if not bars:
        raise PriceNotFoundError(f"no bar of {symbol} on {session}")
    return bars[-1]


def get_price(symbol: str, session: dt.date, sources: Sequence[PriceSource] = SOURCES) -> Price:
    """First source that answers wins."""
    errors = []
    for source in sources:
        try:
            return fetch(source, symbol, session)
        except Exception as error:
            errors.append(f"{source.name}: {type(error).__name__}: {error}")
    raise RuntimeError("all sources failed: " + "; ".join(errors))


def pause_between(index: int, delay: float, sleep: Callable[[float], None]) -> None:
    """Wait `delay` seconds before every symbol except the first (`i` is 1-based)."""
    if index > 1:
        sleep(delay)


def main(
    symbols_csv: Path = Path("data/hose_symbols.csv"),
    output_json: Path = Path("out/vn_stock_latest_prices.json"),
    sources: Sequence[PriceSource] = SOURCES,
    delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    log: Logger = logger,
    session: dt.date | None = None,
) -> int:
    session = session or from_env()
    symbols = read_symbols(symbols_csv)
    prices: list[Price] = []
    skipped: list[str] = []
    for index, symbol in enumerate(symbols, 1):
        pause_between(index, delay, sleep)
        try:
            price = get_price(symbol, session, sources)
        except RuntimeError as error:
            skipped.append(symbol)
            log.warning("[%d/%d] %s skipped: %s", index, len(symbols), symbol, error)
        else:
            prices.append(price)
            log.info("[%d/%d] %s ok (%s)", index, len(symbols), symbol, price.source)
    log.info("fetched %d, skipped %d: %s", len(prices), len(skipped), " ".join(skipped))
    output_json.unlink(missing_ok=True)  # never leave an earlier run's file looking like today's result
    if not prices:
        log.error("no price fetched, nothing written")
        return NO_DATA
    if len(prices) < MIN_COVERAGE * len(symbols):
        log.error(
            "fetched only %d of %d symbols (minimum %.0f%%), nothing written",
            len(prices),
            len(symbols),
            MIN_COVERAGE * 100,
        )
        return NO_DATA
    output_json.parent.mkdir(parents=True, exist_ok=True)
    rows = [price.model_dump(mode="json") for price in prices]
    output_json.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:3])))
