"""index prices.date

`max(date)` and `date <= today` in scripts/vn_stock_screen.py cannot use the primary key (symbol, date).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30 20:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """CREATE INDEX CONCURRENTLY cannot run in a transaction: commit around it."""
    with op.get_context().autocommit_block():
        op.create_index("ix_prices_date", "prices", ["date"], postgresql_concurrently=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_prices_date", table_name="prices", postgresql_concurrently=True)
