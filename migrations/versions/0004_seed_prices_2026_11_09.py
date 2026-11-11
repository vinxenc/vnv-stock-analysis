"""seed prices 2026-11-09

The session of 2026-11-09 that the daily sync never stored (its store job did not run, and the sync only keeps the
latest bar of each symbol, so nothing refills a missed day). 381 real DNSE bars (adjusted), taken from the artifact of
that day's retrieval job; the 25 symbols that did not trade that day have no row. The file is frozen: an applied
migration never runs again, so to load more data add a new revision and a new file, never edit this one.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11 19:30:00
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

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED = Path(__file__).parents[2] / "data" / "seeds" / "prices_2026_11_09.json.gz"


def upgrade() -> None:
    """Fill the missing (symbol, date) rows: one the daily sync already stored is never replaced by the seed's value.

    $ENVIRONMENT=test skips it, like every seed migration (see 0003).
    """
    if os.environ.get("ENVIRONMENT") == "test":
        return
    with gzip.open(SEED, "rt", encoding="utf-8") as file:
        rows = [{**row, "date": dt.date.fromisoformat(row["date"])} for row in json.load(file)]
    prices = sa.Table("prices", sa.MetaData(), autoload_with=op.get_bind())  # the table as it is at this revision
    op.execute(insert(prices).values(rows).on_conflict_do_nothing(index_elements=["symbol", "date"]))  # 381 rows


def downgrade() -> None:
    """Nothing to undo: the rows cannot be told apart from the daily sync's, and downgrading 0001 drops the table."""
