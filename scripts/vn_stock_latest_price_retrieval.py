"""Fetch the latest daily price of every symbol in a CSV and write them as one JSON array.

Usage: uv run python -m scripts.vn_stock_latest_price_retrieval [symbols_csv] [output_json]
Defaults: data/hose_symbols.csv  out/vn_stock_latest_prices.json
Sources per symbol: DNSE -> VPS -> VNDirect, 1 retry each. A symbol that fails everywhere is skipped.
Exit 0 = at least one price written, 4 = no price at all (no file written), anything else = crash.
"""
import csv
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from libs.prices import DNSE, VPS, Price, PriceNotFoundError, PriceSource, VNDirect
from libs.prices.base import validate_symbol

NO_DATA = 4  # not 1: Python exits 1 on an uncaught error, which must not read as "no data"
SOURCES = (DNSE(), VPS(), VNDirect())


def read_symbols(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as f:
        return [validate_symbol(row["code"]) for row in csv.DictReader(f)]


def get_price(
    symbol: str,
    sources: Sequence[PriceSource] = SOURCES,
    retries: int = 1,
    retry_delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Price:
    """First source that answers wins; each gets `retries` extra tries, except on PriceNotFoundError."""
    errors = []
    for source in sources:
        for attempt in range(retries + 1):
            try:
                return source.get_latest_price(symbol)
            except Exception as e:
                error = f"{source.name}: {type(e).__name__}: {e}"
                if isinstance(e, PriceNotFoundError):
                    break  # an unknown ticker will not appear on a second try
                if attempt < retries:
                    sleep(retry_delay)
        errors.append(error)
    raise RuntimeError("all sources failed: " + "; ".join(errors))


def main(
    symbols_csv: Path = Path("data/hose_symbols.csv"),
    output_json: Path = Path("out/vn_stock_latest_prices.json"),
    sources: Sequence[PriceSource] = SOURCES,
    delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    symbols = read_symbols(symbols_csv)
    prices: list[Price] = []
    skipped: list[str] = []
    for i, symbol in enumerate(symbols, 1):
        if i > 1:
            sleep(delay)
        try:
            price = get_price(symbol, sources, retry_delay=delay, sleep=sleep)
        except RuntimeError as e:
            skipped.append(symbol)
            print(f"[{i}/{len(symbols)}] {symbol} skipped: {e}", flush=True)
        else:
            prices.append(price)
            print(f"[{i}/{len(symbols)}] {symbol} ok ({price.source})", flush=True)
    print(f"fetched {len(prices)}, skipped {len(skipped)}: {' '.join(skipped)}", flush=True)
    if not prices:
        print("no price fetched, nothing written", file=sys.stderr)
        return NO_DATA
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps([p.model_dump(mode="json") for p in prices], indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:3])))
