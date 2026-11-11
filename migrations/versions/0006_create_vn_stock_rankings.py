"""create vn_stock_rankings

The ranked shortlist of every screened session, one row per timeframe and symbol (`out/vn_stock_analysis.json` kept
for good). The Postgres enum `timeframe` is created with the table; only `daily` is written so far.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vn_stock_rankings",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("timeframe", sa.Enum("daily", "weekly", "monthly", name="timeframe"), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("turnover", sa.Float(), nullable=False),
        sa.Column("themes", postgresql.JSONB(), nullable=False),
        sa.Column("flags", postgresql.JSONB(), nullable=False),
        sa.Column("indicators", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("date", "timeframe", "symbol"),
    )


def downgrade() -> None:
    op.drop_table("vn_stock_rankings")
    sa.Enum(name="timeframe").drop(op.get_bind())
