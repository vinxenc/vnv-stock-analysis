"""create vn_stock_screen_history

The sessions `vn_stock_screen` has screened. Seeded with 2026-11-10, the baseline: the next run screens the working
day after it (2026-11-11). 2026-11-10 itself is never screened: its run failed on the missing 2026-11-09 bars.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11 19:35:00
"""

import datetime as dt
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the table, then (not under $ENVIRONMENT=test, like every seed migration) insert the baseline."""
    table = op.create_table(
        "vn_stock_screen_history", sa.Column("date", sa.Date(), nullable=False), sa.PrimaryKeyConstraint("date")
    )
    if os.environ.get("ENVIRONMENT") != "test":
        op.bulk_insert(table, [{"date": dt.date(2026, 11, 10)}])


def downgrade() -> None:
    op.drop_table("vn_stock_screen_history")
