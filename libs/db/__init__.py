import os
import re

from sqlalchemy import Engine
from sqlmodel import create_engine


def database_url() -> str:
    """$DATABASE_URL for SQLAlchemy + psycopg 3. Hosts hand out `postgres://`, which SQLAlchemy cannot load."""
    return re.sub(r"^postgres(ql)?(\+psycopg)?://", "postgresql+psycopg://", os.environ["DATABASE_URL"])


def connect() -> Engine:
    """Engine for $DATABASE_URL that gives up instead of hanging on a dead host (10 s) or a held lock (60 s)."""
    return create_engine(database_url(), connect_args={"connect_timeout": 10, "options": "-c statement_timeout=60000"})
