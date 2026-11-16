import os
import re

from sqlalchemy import Connection, Engine, event
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel, create_engine

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


def upsert(connection: Connection, model: type[SQLModel], rows: list[dict]) -> None:
    """`INSERT ... ON CONFLICT (primary key) DO UPDATE` of `rows` (keyed by column name): a row that exists gets every
    other column overwritten, also the ones `rows` leaves out, which take their default (a new `created_at`, a null)."""
    statement = insert(model)
    keys = model.__table__.primary_key.columns
    update = {column.key: column for column in statement.excluded if column.key not in keys}
    connection.execute(statement.on_conflict_do_update(index_elements=keys, set_=update), rows)
