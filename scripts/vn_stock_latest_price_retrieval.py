"""Fetch the daily bars of the sessions due (`$SESSIONS`, `first..last`, see vn_stock_price_sync_session; default
today) of every symbol in a CSV, one request per symbol, and write them as one JSON array.

Usage: uv run python -m scripts.vn_stock_latest_price_retrieval [symbols_csv] [output_json]
Defaults: data/hose_symbols.csv  out/vn_stock_latest_prices.json
Sources per symbol: DNSE -> VPS -> VNDirect, 1 retry each (tenacity). A symbol that fails everywhere is skipped.
A session is written when at least MIN_COVERAGE of the symbols have a bar on it. One below it after the newest such
session is left out and stays due (a partial outage, or bars not published yet: they never reach the database); one
below it before that session is dropped, since a retry asks the same span and would not fill it (a market closure
`scripts/vn_holiday.py` does not know, with a few stray bars). A working day without any bar is logged as a closure.
Exit 0 = prices written, 4 = no session with enough bars (no file written), anything else = crash.
"""

import csv
import datetime as dt
import json
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed

from libs.constants import MIN_COVERAGE, NO_DATA
from libs.logger import Logger, LogxideLogger
from libs.prices import DNSE, VPS, Price, PriceNotFoundError, PriceSource, VNDirect
from libs.prices.base import validate_symbol
from scripts.vn_holiday import working_days
from scripts.vn_stock_price_sync_session import from_env

SOURCES = (DNSE(), VPS(), VNDirect())
logger = LogxideLogger("vn_stock_latest_price_retrieval")


def read_symbols(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(dict.fromkeys(validate_symbol(row["code"]) for row in csv.DictReader(file)))  # dedupe, keep order


@retry(
    stop=stop_after_attempt(2), wait=wait_fixed(1), retry=retry_if_not_exception_type(PriceNotFoundError), reraise=True
)
def fetch(source: PriceSource, symbol: str, first: dt.date, last: dt.date) -> list[Price]:
    """One source, 1 retry after a failure; an unknown ticker, or no bar in the span (halted, not published yet),
    will not appear on a second try, so no retry then. A bar outside the span is dropped."""
    bars = [bar for bar in source.get_history(symbol, first, last) if first <= bar.date <= last]
    if not bars:
        raise PriceNotFoundError(f"no bar of {symbol} from {first} to {last}")
    return bars


def get_prices(symbol: str, first: dt.date, last: dt.date, sources: Sequence[PriceSource] = SOURCES) -> list[Price]:
    """First source that answers wins."""
    errors = []
    for source in sources:
        try:
            return fetch(source, symbol, first, last)
        except Exception as error:
            errors.append(f"{source.name}: {type(error).__name__}: {error}")
    raise RuntimeError("all sources failed: " + "; ".join(errors))


def covered(prices: list[Price], first: dt.date, last: dt.date, symbols: int, log: Logger) -> list[Price]:
    """The bars of the sessions at least MIN_COVERAGE of the symbols have a bar on (see the module docstring)."""
    counts = Counter(price.date for price in prices)
    closure = "a market closure missing from CLOSURES (scripts/vn_holiday.py)?"
    for day in working_days(first, last):
        if day not in counts:
            log.warning("no symbol has a bar on %s: %s", day, closure)
    kept = {day for day, count in counts.items() if count >= MIN_COVERAGE * symbols}
    for day in sorted(set(counts) - kept):
        fate = f"dropped, {closure}" if kept and day < max(kept) else "left out, it stays due"
        log.warning("only %d of %d symbols have a bar on %s (minimum %.0f%%): %s", counts[day], symbols, day,
                    MIN_COVERAGE * 100, fate)  # fmt: skip
    return [price for price in prices if price.date in kept]


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
    sessions: tuple[dt.date, dt.date] | None = None,
) -> int:
    first, last = sessions or from_env()
    symbols = read_symbols(symbols_csv)
    prices: list[Price] = []
    skipped: list[str] = []
    for index, symbol in enumerate(symbols, 1):
        pause_between(index, delay, sleep)
        try:
            bars = get_prices(symbol, first, last, sources)
        except RuntimeError as error:
            skipped.append(symbol)
            log.warning("[%d/%d] %s skipped: %s", index, len(symbols), symbol, error)
        else:
            prices += bars
            log.info("[%d/%d] %s ok (%s)", index, len(symbols), symbol, bars[-1].source)
    log.info("fetched %d, skipped %d: %s", len(symbols) - len(skipped), len(skipped), " ".join(skipped))
    output_json.unlink(missing_ok=True)  # never leave an earlier run's file looking like today's result
    if not prices:
        log.error("no price fetched, nothing written")
        return NO_DATA
    prices = covered(prices, first, last, len(symbols), log)
    if not prices:
        log.error("no session from %s to %s has enough bars, nothing written", first, last)
        return NO_DATA
    output_json.parent.mkdir(parents=True, exist_ok=True)
    rows = [price.model_dump(mode="json") for price in prices]
    output_json.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:3])))
