"""vn_stock_rankings stores scored symbols only

`vn_stock_analyze` no longer stores insufficient data (null) or 0 points: delete the rows the first run wrote
(2026-11-11 had one null score), then make `score` NOT NULL so the table cannot drift back.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-11 21:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM vn_stock_rankings WHERE score IS NULL OR score = 0")
    op.alter_column("vn_stock_rankings", "score", nullable=False)


def downgrade() -> None:
    """The deleted rows are not restored: the JSON artifact of that run still has them."""
    op.alter_column("vn_stock_rankings", "score", nullable=True)
