"""Upsert the prices of a JSON array (see vn_stock_latest_price_retrieval) into the `vn_stock_prices` table, and
record their session in `vn_stock_price_sync_history` in the same transaction: the next sync fetches the working day
after it (vn_stock_price_sync_session). The file holds the bars of one session; more than one date is a crash.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_daily_price_store [input_json]
Default: out/vn_stock_latest_prices.json
A row with the same (symbol, date) is overwritten, so running it twice stores the same data once.
Exit 0 = rows stored, 4 = the file holds no price (nothing stored), anything else = crash.
"""

import datetime as dt
import json
import sys
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from libs.constants import NO_DATA
from libs.db import connect
from libs.db.models import Price, PriceSyncHistory
from libs.logger import Logger, LogxideLogger

logger = LogxideLogger("vn_stock_daily_price_store")


def read_prices(path: Path) -> list[Price]:
    """Validate every row: one bad row fails the whole load before anything is written.

    Two rows with the same (symbol, date) would make Postgres reject the whole upsert: the last one wins.
    """
    prices = (Price.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8")))
    return list({(price.symbol, price.date): price for price in prices}.values())


def store(prices: list[Price], engine: Engine, session: dt.date | None = None) -> None:
    """One INSERT ... ON CONFLICT (symbol, date) DO UPDATE in one transaction: all rows or none. With `session`, the
    same transaction records it as synced."""
    statement = insert(Price).values([price.model_dump() for price in prices])
    columns = Price.__table__.columns
    changed = {column.name: statement.excluded[column.name] for column in columns if not column.primary_key}
    with engine.begin() as connection:
        connection.execute(statement.on_conflict_do_update(index_elements=["symbol", "date"], set_=changed))
        if session:
            connection.execute(insert(PriceSyncHistory).values(date=session).on_conflict_do_nothing())


def main(
    input_json: Path = Path("out/vn_stock_latest_prices.json"), engine: Engine | None = None, log: Logger = logger
) -> int:
    prices = read_prices(input_json)
    if not prices:
        log.error("%s holds no price, nothing stored", input_json)
        return NO_DATA
    sessions = {price.date for price in prices}
    if len(sessions) > 1:
        raise ValueError(f"{input_json} holds the bars of {len(sessions)} sessions, not one: nothing stored")
    session = sessions.pop()
    store(prices, engine or connect(), session)
    log.info("stored %d prices of %s", len(prices), session)
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
