import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlmodel import SQLModel, create_engine

from scripts.vn_stock_daily_price_store import read_prices, store

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
    engine = create_engine(pg_url)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def real_prices(engine: Engine) -> Engine:
    """`engine` seeded with real DNSE history (fetched 2026-10-29, 2026-09-15..2026-10-29): HPG, very liquid (20-session
    average turnover ~395 billion VND), and AAM, almost untraded (~0.02 billion VND)."""
    store(read_prices(Path(__file__).parent / "data" / "prices_hpg_aam.json"), engine)
    return engine
