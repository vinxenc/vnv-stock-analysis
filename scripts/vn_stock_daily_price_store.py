"""Upsert the prices of a JSON array (see vn_stock_latest_price_retrieval) into the `vn_stock_prices` table, and
record every session they hold in `vn_stock_price_sync_history` (one row each) in the same transaction: the next sync
fetches from the working day after the newest one (vn_stock_price_sync_session). The file may hold several sessions.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_daily_price_store [input_json]
Default: out/vn_stock_latest_prices.json
A row with the same (symbol, date) is overwritten, so running it twice stores the same data once.
Exit 0 = rows stored, 4 = the file holds no price (nothing stored), anything else = crash.
"""

import datetime as dt
import json
import sys
from pathlib import Path

from sqlalchemy import Connection, Engine
from sqlalchemy.dialects.postgresql import insert

from libs.constants import NO_DATA
from libs.db import connect
from libs.db.models import Price, PriceSyncHistory
from libs.logger import Logger, LogxideLogger

CHUNK = 5000  # rows per INSERT: 9 columns each stays under the 65,535 parameters Postgres takes in one statement
logger = LogxideLogger("vn_stock_daily_price_store")


def read_prices(path: Path) -> list[Price]:
    """Validate every row: one bad row fails the whole load before anything is written.

    Two rows with the same (symbol, date) would make Postgres reject the whole upsert: the last one wins.
    """
    prices = (Price.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8")))
    return list({(price.symbol, price.date): price for price in prices}.values())


def upsert(connection: Connection, prices: list[Price]) -> None:
    """INSERT ... ON CONFLICT (symbol, date) DO UPDATE, CHUNK rows per statement, in the caller's transaction."""
    columns = Price.__table__.columns
    for start in range(0, len(prices), CHUNK):
        statement = insert(Price).values([price.model_dump() for price in prices[start : start + CHUNK]])
        changed = {column.name: statement.excluded[column.name] for column in columns if not column.primary_key}
        connection.execute(statement.on_conflict_do_update(index_elements=["symbol", "date"], set_=changed))


def store(prices: list[Price], engine: Engine, synced: list[dt.date]) -> None:
    """Upsert in one transaction, all rows or none, and record the sessions `synced` in the same transaction."""
    with engine.begin() as connection:
        upsert(connection, prices)
        connection.execute(insert(PriceSyncHistory).values([{"date": day} for day in synced]).on_conflict_do_nothing())


def main(
    input_json: Path = Path("out/vn_stock_latest_prices.json"), engine: Engine | None = None, log: Logger = logger
) -> int:
    prices = read_prices(input_json)
    if not prices:
        log.error("%s holds no price, nothing stored", input_json)
        return NO_DATA
    sessions = sorted({price.date for price in prices})
    store(prices, engine or connect(), sessions)
    log.info("stored %d prices of %d sessions, %s to %s", len(prices), len(sessions), sessions[0], sessions[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
