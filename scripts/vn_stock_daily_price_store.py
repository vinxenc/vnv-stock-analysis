"""Upsert the latest price of every symbol of a JSON array (see vn_stock_latest_price_retrieval) into
`vn_stock_prices`, after applying the dividend adjustments its older bars show.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_daily_price_store [input_json]
Default: out/vn_stock_latest_prices.json
Per symbol, only the newest bar of the file is upserted: a row with the same (symbol, date) is overwritten, so running
it twice stores the same data once. The older bars are evidence only (`libs/prices/adjustment.py`): when the source's
bars are the stored ones times one factor, every stored bar of the symbol up to the last changed one is multiplied by it
(volume unchanged), the source's own bars replace those it returned, and the adjustment is logged in
`vn_stock_price_adjustments`, all in the same transaction as the upsert. Bars that moved in another way are logged as a
warning and left alone, the newest bar too when it is stored and moved with the same volume. More than MAX_ADJUSTED
symbols adjusted in one run stores nothing: that is a source changing its quotes, not dividends.
Exit 0 = rows stored, 4 = the file holds no price (nothing stored), anything else = crash.
"""

import json
import sys
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
    factor = adjustment.factor
    bars = connection.execute(
        update(Price)
        .where(Price.symbol == adjustment.symbol, Price.date <= adjustment.through)
        .values(open=Price.open * factor, high=Price.high * factor, low=Price.low * factor, close=Price.close * factor)
    ).rowcount
    _upsert(connection, adjustment.fetched)
    connection.execute(
        insert(PriceAdjustment).values(
            symbol=adjustment.symbol, through=adjustment.through, factor=factor, source=adjustment.source, bars=bars
        )
    )
    return bars


def store(prices: list[Price], engine: Engine, log: Logger = logger) -> list[Adjustment]:
    """In one transaction: the adjustments the older bars show, then the newest bar of every symbol. All or nothing."""
    by_symbol: dict[str, list[Price]] = {}
    for price in sorted(prices, key=lambda price: (price.symbol, price.date)):
        by_symbol.setdefault(price.symbol, []).append(price)
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
            bars = _adjust(connection, adjustment)
            log.info(
                "%s adjusted through %s by %.4f (%s, %d bars)",
                adjustment.symbol,
                adjustment.through,
                adjustment.factor,
                adjustment.source,
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
