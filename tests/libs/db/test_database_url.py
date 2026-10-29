import pytest
from sqlalchemy import text

from libs.db import connect, database_url


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgres+psycopg", "postgresql+psycopg"])
def test_database_url_forces_psycopg3_and_keeps_the_rest(monkeypatch: pytest.MonkeyPatch, scheme: str) -> None:
    monkeypatch.setenv("DATABASE_URL", f"{scheme}://user:p%40ss@host:12345/db?sslmode=require")
    assert database_url() == "postgresql+psycopg://user:p%40ss@host:12345/db?sslmode=require"


def test_connect_sets_timeouts(monkeypatch: pytest.MonkeyPatch, pg_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_url)
    engine = connect()
    with engine.connect() as connection:
        assert connection.execute(text("SHOW statement_timeout")).scalar() == "1min"
    engine.dispose()
