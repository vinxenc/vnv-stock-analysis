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
    """CREATE INDEX CONCURRENTLY cannot run in a transaction: commit around it.

    A build that failed or timed out leaves an INVALID index of the same name, which would make a retry fail: drop it
    first (the migration only runs again when the index is absent or invalid). No statement timeout, the build may be
    long, but a bounded lock wait: a conflicting transaction must fail the job, not queue the later migrations.
    """
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '10s'")
        op.drop_index("ix_prices_date", table_name="prices", postgresql_concurrently=True, if_exists=True)
        op.create_index("ix_prices_date", "prices", ["date"], postgresql_concurrently=True)
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_prices_date", table_name="prices", postgresql_concurrently=True)
