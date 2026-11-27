import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import Engine, insert

from libs.constants import VN_TZ
from libs.db.models import PriceSyncHistory
from scripts.vn_stock_price_sync_session import due_sessions, from_env, main

FRIDAY = dt.date(2026, 11, 27)
MONDAY = dt.date(2026, 11, 30)


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), VN_TZ)


def synced(engine: Engine, *days: dt.date) -> None:
    with engine.begin() as connection:
        connection.execute(insert(PriceSyncHistory), [{"date": day} for day in days])


def test_the_working_day_after_the_newest_session(engine: Engine) -> None:
    synced(engine, FRIDAY - dt.timedelta(days=1), FRIDAY - dt.timedelta(days=2))
    assert due_sessions(engine, at(FRIDAY, 14, 45)) == (FRIDAY, FRIDAY)


def test_missed_sessions_are_caught_up_at_once(engine: Engine) -> None:
    synced(engine, FRIDAY)
    assert due_sessions(engine, at(MONDAY + dt.timedelta(days=3), 15)) == (MONDAY, MONDAY + dt.timedelta(days=3))


def test_a_run_delayed_past_midnight_still_fetches_friday(engine: Engine) -> None:
    """The wall clock says Saturday, a day off: the session is still Friday's."""
    synced(engine, FRIDAY - dt.timedelta(days=1))
    assert due_sessions(engine, at(FRIDAY + dt.timedelta(days=1), 0, 30)) == (FRIDAY, FRIDAY)


def test_a_run_before_the_close_stops_at_the_previous_session(engine: Engine) -> None:
    synced(engine, FRIDAY - dt.timedelta(days=2))
    assert due_sessions(engine, at(FRIDAY, 10)) == (FRIDAY - dt.timedelta(days=1),) * 2


def test_monday_follows_friday(engine: Engine) -> None:
    synced(engine, FRIDAY)
    assert due_sessions(engine, at(MONDAY, 14, 50)) == (MONDAY, MONDAY)


def test_nothing_is_due_before_the_close_or_on_a_day_off(engine: Engine) -> None:
    synced(engine, FRIDAY - dt.timedelta(days=1))
    assert due_sessions(engine, at(FRIDAY, 14, 44)) is None
    synced(engine, FRIDAY)
    assert due_sessions(engine, at(FRIDAY + dt.timedelta(days=1), 15)) is None  # Saturday: Monday is not due yet


def test_an_empty_history_fetches_the_newest_closed_session(engine: Engine) -> None:
    assert due_sessions(engine, at(FRIDAY, 15)) == (FRIDAY, FRIDAY)
    assert due_sessions(engine, at(FRIDAY + dt.timedelta(days=1), 15)) == (FRIDAY, FRIDAY)  # Saturday: a day off


def test_main_writes_the_sessions_for_the_next_jobs(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    synced(engine, FRIDAY - dt.timedelta(days=2))
    assert main(engine, at(FRIDAY, 15)) == 0
    assert output.read_text(encoding="utf-8") == "sessions=2026-11-26..2026-11-27\n"


def test_main_nothing_due_writes_nothing(engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    synced(engine, FRIDAY)
    assert main(engine, at(FRIDAY, 20)) == 0
    assert not output.exists()


def test_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSIONS", "2026-11-23..2026-11-26")
    assert from_env() == (dt.date(2026, 11, 23), dt.date(2026, 11, 26))
    monkeypatch.setenv("SESSIONS", "2026-11-26")
    assert from_env() == (dt.date(2026, 11, 26),) * 2
    monkeypatch.delenv("SESSIONS")
    assert from_env() == (dt.datetime.now(VN_TZ).date(),) * 2
