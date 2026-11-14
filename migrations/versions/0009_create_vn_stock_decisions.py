"""create vn_stock_decisions

One answer (buy or skip, with the probability of buy) of one decider about one symbol of one session, and its
outcome five sessions later (`return_5`, `hit`: null until known). `decider`, `decision` and `probability` are
guarded by CHECK constraints, not a Postgres enum: a fourth decider is a new migration that swaps one constraint.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-14 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vn_stock_decisions",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("decider", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("return_5", sa.Float(), nullable=True),
        sa.Column("hit", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("date", "symbol", "decider"),
        sa.CheckConstraint("decider IN ('claude', 'jev', 'tabicl')", name="ck_vn_stock_decisions_decider"),
        sa.CheckConstraint("decision IN ('buy', 'skip')", name="ck_vn_stock_decisions_decision"),
        sa.CheckConstraint("probability BETWEEN 0 AND 1", name="ck_vn_stock_decisions_probability"),
    )


def downgrade() -> None:
    op.drop_table("vn_stock_decisions")
