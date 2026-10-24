"""Fetch the latest daily price of every symbol in a CSV and write them as one JSON array.

Usage: uv run python -m scripts.vn_stock_latest_price_retrieval [symbols_csv] [output_json]
Defaults: data/hose_symbols.csv  out/vn_stock_latest_prices.json
Sources per symbol: DNSE -> VPS -> VNDirect, 1 retry each (tenacity). A symbol that fails everywhere is skipped.
Exit 0 = at least one price written, 4 = no price at all (no file written), anything else = crash.
"""
import csv
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed

from libs.logger import Logger, LogxideLogger
from libs.prices import DNSE, VPS, Price, PriceNotFoundError, PriceSource, VNDirect
from libs.prices.base import validate_symbol

NO_DATA = 4  # not 1: Python exits 1 on an uncaught error, which must not read as "no data"
SOURCES = (DNSE(), VPS(), VNDirect())
logger = LogxideLogger("vn_stock_latest_price_retrieval")


def read_symbols(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(dict.fromkeys(validate_symbol(row["code"]) for row in csv.DictReader(f)))  # dedupe, keep order


@retry(
    stop=stop_after_attempt(2), wait=wait_fixed(2), retry=retry_if_not_exception_type(PriceNotFoundError), reraise=True
)
def fetch(source: PriceSource, symbol: str) -> Price:
    """One source, 1 retry after a failure; an unknown ticker will not appear on a second try, so no retry then."""
    return source.get_latest_price(symbol)


def get_price(symbol: str, sources: Sequence[PriceSource] = SOURCES) -> Price:
    """First source that answers wins."""
    errors = []
    for source in sources:
        try:
            return fetch(source, symbol)
        except Exception as e:
            errors.append(f"{source.name}: {type(e).__name__}: {e}")
    raise RuntimeError("all sources failed: " + "; ".join(errors))


def pause_between(i: int, delay: float, sleep: Callable[[float], None]) -> None:
    """Wait `delay` seconds before every symbol except the first (`i` is 1-based)."""
    if i > 1:
        sleep(delay)


def main(
    symbols_csv: Path = Path("data/hose_symbols.csv"),
    output_json: Path = Path("out/vn_stock_latest_prices.json"),
    sources: Sequence[PriceSource] = SOURCES,
    delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    log: Logger = logger,
) -> int:
    symbols = read_symbols(symbols_csv)
    prices: list[Price] = []
    skipped: list[str] = []
    for i, symbol in enumerate(symbols, 1):
        pause_between(i, delay, sleep)
        try:
            price = get_price(symbol, sources)
        except RuntimeError as e:
            skipped.append(symbol)
            log.warning("[%d/%d] %s skipped: %s", i, len(symbols), symbol, e)
        else:
            prices.append(price)
            log.info("[%d/%d] %s ok (%s)", i, len(symbols), symbol, price.source)
    log.info("fetched %d, skipped %d: %s", len(prices), len(skipped), " ".join(skipped))
    if not prices:
        log.error("no price fetched, nothing written")
        output_json.unlink(missing_ok=True)  # never leave an earlier run's file looking like today's result
        return NO_DATA
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps([p.model_dump(mode="json") for p in prices], indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:3])))
