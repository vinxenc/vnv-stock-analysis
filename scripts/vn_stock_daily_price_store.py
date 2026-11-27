"""Upsert the newest bar of every symbol of a JSON array (see vn_stock_latest_price_retrieval) into `vn_stock_prices`,
after the dividend adjustments its older bars show (`libs/prices/adjustment.py`), in one transaction.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_daily_price_store [input_json]
Default: out/vn_stock_latest_prices.json
Exit 0 = rows stored, 4 = the file holds no price (nothing stored), anything else = crash.
"""

import json
import sys
from itertools import groupby
from operator import attrgetter
from pathlib import Path

from sqlalchemy import Connection, Engine, select, update
from sqlalchemy.dialects.postgresql import insert

from libs.constants import NO_DATA
from libs.db import connect
from libs.db.models import Price, PriceAdjustment
from libs.logger import Logger, LogxideLogger
from libs.prices.adjustment import Adjustment, InconsistentBars, detect, moved

MAX_ADJUSTED = 20  # symbols per run; the nights seen so far had 2 and 3
logger = LogxideLogger("vn_stock_daily_price_store")


def read_prices(path: Path) -> list[Price]:
    """Validate every row: one bad row fails the whole load before anything is written.

    Two rows with the same (symbol, date) would make Postgres reject the whole upsert: the last one wins.
    """
    prices = (Price.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8")))
    return list({(price.symbol, price.date): price for price in prices}.values())


def _upsert(connection: Connection, prices: list[Price]) -> None:
    """INSERT ... ON CONFLICT (symbol, date) DO UPDATE."""
    statement = insert(Price).values([price.model_dump() for price in prices])
    columns = Price.__table__.columns
    changed = {column.name: statement.excluded[column.name] for column in columns if not column.primary_key}
    connection.execute(statement.on_conflict_do_update(index_elements=["symbol", "date"], set_=changed))


def _adjust(connection: Connection, adjustment: Adjustment) -> int:
    """Multiply every stored price of the symbol up to `through`, put the source's own bars over the ones it returned,
    log it. Returns the bars changed."""
    factor, last = adjustment.factor, adjustment.fetched[-1]
    bars = connection.execute(
        update(Price)
        .where(Price.symbol == last.symbol, Price.date <= last.date)
        .values(open=Price.open * factor, high=Price.high * factor, low=Price.low * factor, close=Price.close * factor)
    ).rowcount
    _upsert(connection, adjustment.fetched)
    connection.execute(
        insert(PriceAdjustment).values(
            symbol=last.symbol, through=last.date, factor=factor, source=last.source, bars=bars
        )
    )
    return bars


def store(prices: list[Price], engine: Engine, log: Logger = logger) -> list[Adjustment]:
    """In one transaction: the adjustments the older bars show, then the newest bar of every symbol. All or nothing."""
    ordered = sorted(prices, key=attrgetter("symbol", "date"))
    by_symbol = {symbol: list(bars) for symbol, bars in groupby(ordered, key=attrgetter("symbol"))}
    with engine.begin() as connection:
        query = select(Price).where(Price.symbol.in_(by_symbol), Price.date >= min(price.date for price in prices))
        stored: dict[str, dict] = {symbol: {} for symbol in by_symbol}
        for row in connection.execute(query).mappings():
            stored[row["symbol"]][row["date"]] = Price.model_validate(dict(row))
        adjustments = []
        newest = {symbol: bars[-1] for symbol, bars in by_symbol.items()}
        for symbol, bars in by_symbol.items():
            try:
                adjustment = detect(bars, stored[symbol])
            except InconsistentBars as error:
                log.warning("not adjusted: %s", error)
                old = stored[symbol].get(bars[-1].date)
                # a moved newest bar with the same volume may be a lone adjusted one: keep the stored bar; another
                # volume is a correction of the day, upserted as always
                if old and old.volume == bars[-1].volume and moved(bars[-1], old):
                    del newest[symbol]
                continue
            if adjustment:
                adjustments.append(adjustment)
        if len(adjustments) > MAX_ADJUSTED:
            raise RuntimeError(
                f"{len(adjustments)} symbols would be adjusted (more than {MAX_ADJUSTED}): stored nothing"
            )
        for adjustment in adjustments:
            last, bars = adjustment.fetched[-1], _adjust(connection, adjustment)
            log.info(
                "%s adjusted through %s by %.4f (%s, %d bars)",
                last.symbol,
                last.date,
                adjustment.factor,
                last.source,
                bars,
            )
        if newest:
            _upsert(connection, list(newest.values()))
    return adjustments


def main(
    input_json: Path = Path("out/vn_stock_latest_prices.json"), engine: Engine | None = None, log: Logger = logger
) -> int:
    prices = read_prices(input_json)
    if not prices:
        log.error("%s holds no price, nothing stored", input_json)
        return NO_DATA
    adjustments = store(prices, engine or connect(), log)
    log.info("stored %d prices, %d symbols adjusted", len({price.symbol for price in prices}), len(adjustments))
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
