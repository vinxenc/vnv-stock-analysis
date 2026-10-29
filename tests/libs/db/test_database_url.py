import pytest
from sqlalchemy import Engine, text

from libs.db import connect, database_url, log_sql


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgres+psycopg", "postgresql+psycopg"])
def test_database_url_forces_psycopg3_and_keeps_the_rest(monkeypatch: pytest.MonkeyPatch, scheme: str) -> None:
    monkeypatch.setenv("DATABASE_URL", f"{scheme}://user:p%40ss@host:12345/db?sslmode=require")
    assert database_url() == "postgresql+psycopg://user:p%40ss@host:12345/db?sslmode=require"


def test_connect_sets_timeouts(monkeypatch: pytest.MonkeyPatch, pg_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_url)
    engine = connect()
    with engine.connect() as connection:
        assert connection.execute(text("SHOW statement_timeout")).scalar() == "1min"
        assert connection.connection.dbapi_connection.info.get_parameters()["connect_timeout"] == "10"
    engine.dispose()


def test_log_sql_logs_statements_only_when_asked(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str], engine: Engine
) -> None:
    monkeypatch.delenv("SQL_LOG_ENABLE", raising=False)
    with log_sql(engine).connect() as connection:
        connection.execute(text("SELECT 11111"))
    assert "11111" not in capfd.readouterr().err
    monkeypatch.setenv("SQL_LOG_ENABLE", "1")
    with log_sql(engine).connect() as connection:
        connection.execute(text("SELECT :value"), {"value": 22222})
    assert "22222" in capfd.readouterr().err  # the parameter, so statement and parameters are both logged
