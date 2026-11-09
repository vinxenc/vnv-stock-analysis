"""seed prices 2025-01-02..2026-11-06

Real daily history (DNSE, adjusted) of every symbol in data/hose_symbols.csv, so a new database starts with a year and
a half of prices. The file is frozen: an applied migration never runs again, so to load more data add a new revision
and a new file, never edit this one.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09 21:00:00
"""

import datetime as dt
import gzip
import json
import os
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED = Path(__file__).parents[2] / "data" / "seeds" / "prices_2025_2026.json.gz"
BATCH = 5000  # 9 columns x 5000 rows stays under Postgres' 65535 bind parameters per statement

# a frozen copy of the table: a migration must not import the models, which change after it
prices = sa.table(
    "prices",
    sa.column("symbol", sa.String),
    sa.column("date", sa.Date),
    sa.column("source", sa.String),
    sa.column("unit", sa.String),
    sa.column("open", sa.Float),
    sa.column("high", sa.Float),
    sa.column("low", sa.Float),
    sa.column("close", sa.Float),
    sa.column("volume", sa.BigInteger),
)


def upgrade() -> None:
    """Fill the missing (symbol, date) rows: one the daily sync already stored is never replaced by the seed's value.

    $APP_ENV=test skips it (the unit tests migrate often and need no data): every seed migration honours it. Never set
    it on a database that must receive the seed, the revision would be recorded as applied without its rows.
    """
    if os.environ.get("APP_ENV") == "test":
        return
    with gzip.open(SEED, "rt", encoding="utf-8") as file:
        rows = [{**row, "date": dt.date.fromisoformat(row["date"])} for row in json.load(file)]
    for start in range(0, len(rows), BATCH):
        statement = insert(prices).values(rows[start : start + BATCH])
        op.execute(statement.on_conflict_do_nothing(index_elements=["symbol", "date"]))


def downgrade() -> None:
    """Nothing to undo: the rows cannot be told apart from the daily sync's, and downgrading 0001 drops the table."""
