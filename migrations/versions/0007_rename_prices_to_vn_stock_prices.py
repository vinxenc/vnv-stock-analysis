"""rename prices to vn_stock_prices

Every table is named `vn_stock_<thing>` (see CLAUDE.md); `prices` was the only one left. Renames the table, its primary
key and the `date` index (the model's `index=True` names it `ix_<table>_date`, and `alembic check` compares index names).
A rename only touches the catalog, but it needs an ACCESS EXCLUSIVE lock: a bounded wait, so a running sync makes the
job fail instead of queuing every reader behind it.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-11 21:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def rename(old: str, new: str) -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.rename_table(old, new)
    op.execute(f"ALTER INDEX {old}_pkey RENAME TO {new}_pkey")
    op.execute(f"ALTER INDEX ix_{old}_date RENAME TO ix_{new}_date")


def upgrade() -> None:
    rename("prices", "vn_stock_prices")


def downgrade() -> None:
    rename("vn_stock_prices", "prices")
