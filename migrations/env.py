"""Alembic env: online mode only, database from $DATABASE_URL (e.g. postgresql+psycopg://user:pass@host/db)."""
import os

from alembic import context
from sqlmodel import SQLModel, create_engine

from libs.db import models  # noqa: F401  (registers the table on SQLModel.metadata)

with create_engine(os.environ["DATABASE_URL"]).connect() as connection:
    context.configure(connection=connection, target_metadata=SQLModel.metadata)
    with context.begin_transaction():
        context.run_migrations()
