import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlmodel import SQLModel, create_engine

from libs.db import log_sql

# Never the dev database `vnv`: the tests wipe their tables. `docker compose up -d --wait` provides the server.
SERVER_URL = os.environ.get("TEST_DATABASE_SERVER", "postgresql+psycopg://vnv:vnv@127.0.0.1:5432/postgres")
TEST_DB = "vnv_test"


@pytest.fixture(scope="session")
def pg_url() -> str:
    """URL of the throwaway test database, created on first use."""
    server = create_engine(SERVER_URL, isolation_level="AUTOCOMMIT")
    try:
        with server.connect() as connection:
            exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB})
            if not exists.scalar():
                connection.execute(text(f"CREATE DATABASE {TEST_DB}"))
    except Exception as error:
        pytest.fail(f"Postgres is not reachable ({type(error).__name__}); run `docker compose up -d --wait`")
    finally:
        server.dispose()
    return server.url.set(database=TEST_DB).render_as_string(hide_password=False)


@pytest.fixture
def engine(pg_url: str) -> Iterator[Engine]:
    """Fresh tables for every test."""
    engine = log_sql(create_engine(pg_url))
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()

