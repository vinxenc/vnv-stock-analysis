"""Alembic env: online mode only, database from $DATABASE_URL (postgres:// or postgresql+psycopg://user:pass@host/db)."""
from alembic import context
from sqlmodel import SQLModel, create_engine

from libs.db import database_url, log_sql, models  # noqa: F401  (registers the table on SQLModel.metadata)

with log_sql(create_engine(database_url())).connect() as connection:
    context.configure(connection=connection, target_metadata=SQLModel.metadata)
    with context.begin_transaction():
        context.run_migrations()
