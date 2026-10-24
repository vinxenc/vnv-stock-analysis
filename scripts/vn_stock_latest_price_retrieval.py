"""Fetch the latest daily price of every symbol in a CSV and write them as one JSON array.

Usage: uv run python -m scripts.vn_stock_latest_price_retrieval [symbols_csv] [output_json]
Defaults: data/hose_symbols.csv  out/vn_stock_latest_prices.json
Sources per symbol: DNSE -> VPS -> VNDirect, 1 retry each (tenacity). A symbol that fails everywhere is skipped.
After MAX_RUNTIME the untried symbols are skipped too.
Exit 0 = at least one price written, 4 = no price at all (no file written), anything else = crash.
"""
import csv
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed

from libs.prices import DNSE, VPS, Price, PriceNotFoundError, PriceSource, VNDirect
from libs.prices.base import validate_symbol

MAX_RUNTIME = 50 * 60  # seconds; stop before the workflow's 60 min timeout cancels the job and loses the result
NO_DATA = 4  # not 1: Python exits 1 on an uncaught error, which must not read as "no data"
SOURCES = (DNSE(), VPS(), VNDirect())


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


def main(
    symbols_csv: Path = Path("data/hose_symbols.csv"),
    output_json: Path = Path("out/vn_stock_latest_prices.json"),
    sources: Sequence[PriceSource] = SOURCES,
    delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    max_runtime: float = MAX_RUNTIME,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    started = clock()
    symbols = read_symbols(symbols_csv)
    prices: list[Price] = []
    skipped: list[str] = []
    for i, symbol in enumerate(symbols, 1):
        if clock() - started > max_runtime:
            skipped.extend(symbols[i - 1 :])
            print(f"time limit reached, {len(symbols) - i + 1} symbols not tried", flush=True)
            break
        if i > 1:
            sleep(delay)
        try:
            price = get_price(symbol, sources)
        except RuntimeError as e:
            skipped.append(symbol)
            print(f"[{i}/{len(symbols)}] {symbol} skipped: {e}", flush=True)
        else:
            prices.append(price)
            print(f"[{i}/{len(symbols)}] {symbol} ok ({price.source})", flush=True)
    print(f"fetched {len(prices)}, skipped {len(skipped)}: {' '.join(skipped)}", flush=True)
    if not prices:
        print("no price fetched, nothing written", file=sys.stderr)
        output_json.unlink(missing_ok=True)  # never leave an earlier run's file looking like today's result
        return NO_DATA
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps([p.model_dump(mode="json") for p in prices], indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:3])))
