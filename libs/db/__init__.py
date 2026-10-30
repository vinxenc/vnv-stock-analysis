import os
import re

from sqlalchemy import Engine, event
from sqlalchemy.pool import NullPool
from sqlmodel import create_engine

from libs.logger import LogxideLogger


def database_url() -> str:
    """$DATABASE_URL for SQLAlchemy + psycopg 3. Hosts hand out `postgres://`, which SQLAlchemy cannot load."""
    return re.sub(r"^postgres(ql)?(\+psycopg)?://", "postgresql+psycopg://", os.environ["DATABASE_URL"])


def connect() -> Engine:
    """Engine for $DATABASE_URL that gives up instead of hanging on a dead host (10 s) or a held lock (60 s).

    NullPool: a connection is closed as soon as it is released, so none outlives its `with` block (no pool to dispose).
    Every checkout opens a new connection: do the whole job inside one `with`, not one per row or symbol.
    With SQL_LOG_ENABLE=1, log every statement and its parameters (not `echo=True`: logxide swallows it).
    """
    options = {"connect_timeout": 10, "options": "-c statement_timeout=60000"}
    engine = create_engine(database_url(), connect_args=options, poolclass=NullPool)
    if os.environ.get("SQL_LOG_ENABLE") == "1":
        logger = LogxideLogger("sql")
        event.listen(
            engine,
            "before_cursor_execute",
            lambda connection, cursor, statement, parameters, context, executemany: logger.info(
                "%s %s", " ".join(statement.split()), parameters
            ),
        )
    return engine
