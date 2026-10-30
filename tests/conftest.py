import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlmodel import create_engine

from libs.db import connect

# Never the dev database `vnv`: the tests wipe their tables. `docker compose up -d --wait` provides the server.
SERVER_URL = os.environ.get("TEST_DATABASE_SERVER", "postgresql+psycopg://vnv:vnv@127.0.0.1:5432/postgres")
TEST_DB = "vnv_test"


@pytest.fixture(scope="session")
def pg_url() -> str:
    """URL of the throwaway test database, dropped and recreated at the start of every session, then migrated with the
    real migrations (not `create_all`), so the tests run on the schema production gets."""
    server = create_engine(SERVER_URL, isolation_level="AUTOCOMMIT")
    try:
        with server.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            connection.execute(text(f"CREATE DATABASE {TEST_DB}"))
    except Exception as error:
        pytest.fail(f"Postgres is not reachable ({type(error).__name__}); run `docker compose up -d --wait`")
    finally:
        server.dispose()
    url = server.url.set(database=TEST_DB).render_as_string(hide_password=False)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", url)  # migrations/env.py reads the database from it
        command.upgrade(Config("alembic.ini"), "head")  # pytest runs from the repository root
    return url


@pytest.fixture
def alembic_config(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic config for the test database."""
    monkeypatch.setenv("DATABASE_URL", pg_url)
    return Config("alembic.ini")  # pytest runs from the repository root


@pytest.fixture
def engine(pg_url: str, monkeypatch: pytest.MonkeyPatch) -> Engine:
    """Empty `prices` for every test."""
    monkeypatch.setenv("DATABASE_URL", pg_url)
    engine = connect()
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE prices"))
    return engine
