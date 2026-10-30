"""Alembic env: online mode only, database from $DATABASE_URL (postgres:// or postgresql+psycopg://user:pass@host/db)."""

from alembic import context
from sqlmodel import SQLModel

from libs.db import connect, models  # noqa: F401  (registers the table on SQLModel.metadata)

with connect().connect() as connection:
    context.configure(connection=connection, target_metadata=SQLModel.metadata)
    with context.begin_transaction():
        context.run_migrations()
