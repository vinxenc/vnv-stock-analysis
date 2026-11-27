"""create vn_stock_price_sync_history

The sessions the price sync has stored, like `vn_stock_screen_history` for the screen: the next run fetches from the
working day after the newest one, so a run that GitHub delays past midnight still fetches the right session. Seeded
with 2026-11-20, the baseline: the first run fetches every session from the working day after it (2026-11-23) to the
newest closed one, with their ex-rights symbols. Older ex-rights dates are left as they are.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-27 23:00:00
"""

import datetime as dt
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = op.create_table(
        "vn_stock_price_sync_history", sa.Column("date", sa.Date(), nullable=False), sa.PrimaryKeyConstraint("date")
    )
    op.bulk_insert(table, [{"date": dt.date(2026, 11, 20)}])  # the tests empty the table in their `engine` fixture


def downgrade() -> None:
    op.drop_table("vn_stock_price_sync_history")
