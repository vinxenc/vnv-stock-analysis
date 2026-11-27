"""create vn_stock_price_adjustments

The log of the dividend / split adjustments the price store applied to `vn_stock_prices` (option B: the stored history
is adjusted in place, as of the newest fetch, like the source's own history). One row per adjustment: the symbol, the
last date it adjusted (`through`; the ex-date is a later session, often the next one), the factor every price up to
that date was multiplied by, the source whose bars showed it, how many bars changed and when. Dividing a bar by the
product of the factors of the rows whose `through` is on or after its date gives the price as first stored.
`factor` is guarded by a CHECK (> 0), not by the code alone.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-27 20:00:00
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
        "vn_stock_price_adjustments",
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("through", sa.Date(), nullable=False),
        sa.Column("factor", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("bars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "through"),
        sa.CheckConstraint("factor > 0", name="ck_vn_stock_price_adjustments_factor"),
    )


def downgrade() -> None:
    op.drop_table("vn_stock_price_adjustments")
