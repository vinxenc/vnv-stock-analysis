"""create vn_stock_price_sync_history

The sessions the price sync has stored, like `vn_stock_screen_history` for the screen: the next run fetches the
working day after the newest one, so a run that GitHub delays past midnight still fetches the right session. Seeded
with the newest fully synced date of `vn_stock_prices` (the baseline: the sync before this table recorded nothing);
nothing on an empty database, where the first run fetches today.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-27 23:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vn_stock_price_sync_history", sa.Column("date", sa.Date(), nullable=False), sa.PrimaryKeyConstraint("date")
    )
    # the newest date with a full sync (at least 90% of the most bars any date has): a date with a few bars only
    # (a symbol re-stored by hand ahead of the sync) is not a session done
    op.execute(
        """
        INSERT INTO vn_stock_price_sync_history (date)
        SELECT max(date) FROM (
            SELECT date FROM vn_stock_prices GROUP BY date
            HAVING count(*) >= 0.9 * (SELECT max(n) FROM (SELECT count(*) AS n FROM vn_stock_prices GROUP BY date) AS c)
        ) AS full_dates
        HAVING max(date) IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("vn_stock_price_sync_history")
