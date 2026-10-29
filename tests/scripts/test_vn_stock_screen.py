import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from libs.db.models import Price
from scripts import vn_stock_screen
from scripts.vn_stock_latest_price_retrieval import read_symbols
from scripts.vn_stock_screen import MIN_TURNOVER, NO_DATA, SESSIONS, main, screen

TODAY = dt.date(2026, 10, 23)  # a fixed day in the past, so main()'s default (the real today) never equals it


def store(engine: Engine, *rows: tuple[str, float, int, dt.date]) -> None:
    """(symbol, close, volume, date) rows; prices are in thousand VND, so turnover = close × volume."""
    with Session(engine) as session:
        for symbol, close, volume, date in rows:
            ohlc = dict(open=close, high=close, low=close, close=close)
            session.add(Price.model_validate(dict(symbol=symbol, date=date, source="A", volume=volume, **ohlc)))
        session.commit()


def test_screen_keeps_exactly_the_threshold_and_drops_below_and_halted(engine: Engine) -> None:
    assert MIN_TURNOVER == 20_000_000
    store(
        engine,
        ("AAA", 20_000, 1_000, TODAY),  # exactly 20 billion VND: kept
        ("BBB", 20_000, 999, TODAY),  # just below
        ("CCC", 50, 0, TODAY),  # halted
        ("DDD", 10, 3_000_000, TODAY),  # 30 billion VND: kept
    )
    assert screen(engine, TODAY) == ["AAA", "DDD"]


def days(count: int, end: dt.date = TODAY) -> list[dt.date]:
    """`count` consecutive days ending on `end`."""
    return [end - dt.timedelta(days=count - 1 - i) for i in range(count)]


YESTERDAY = TODAY - dt.timedelta(days=1)


def test_screen_averages_the_last_20_sessions(engine: Engine) -> None:
    assert SESSIONS == 20
    old = TODAY - dt.timedelta(days=30)
    store(
        engine,
        # AAA: 19 quiet days + today 20 billion x 20 = average above the threshold, no matter how quiet the rest was
        *[("AAA", 20_000, 0, d) for d in days(19, YESTERDAY)],
        ("AAA", 20_000, 20_000, TODAY),  # 400 billion today, average = 20 billion: kept
        # BBB: a huge day older than 20 sessions does not count
        ("BBB", 20_000, 10_000_000, old),
        *[("BBB", 20_000, 1_000, d) for d in days(20)],  # 20 billion on each of the last 20: kept
        # CCC: one big day (today) among 20 quiet ones: average 19 billion, dropped
        *[("CCC", 1, 1, d) for d in days(19, YESTERDAY)],
        ("CCC", 20_000, 19_000, TODAY),
    )
    assert screen(engine, TODAY) == ["AAA", "BBB"]


def test_screen_needs_a_row_today(engine: Engine) -> None:
    yesterday = TODAY - dt.timedelta(days=1)
    store(engine, ("AAA", 10, 3_000_000, TODAY), ("BBB", 10, 3_000_000, yesterday))  # BBB has no bar today
    assert screen(engine, TODAY) == ["AAA"]


@pytest.mark.parametrize("stored_date", [TODAY - dt.timedelta(days=1), TODAY + dt.timedelta(days=1)])
def test_screen_fails_when_newest_session_is_not_today(engine: Engine, stored_date: dt.date) -> None:
    store(engine, ("AAA", 10, 3_000_000, stored_date))
    with pytest.raises(RuntimeError, match="late or failed"):
        screen(engine, TODAY)


def test_screen_fails_on_empty_table(engine: Engine) -> None:
    with pytest.raises(RuntimeError, match="None"):
        screen(engine, TODAY)


def test_main_writes_csv_that_read_symbols_reads(tmp_path: Path, engine: Engine) -> None:
    store(engine, ("BBB", 10, 3_000_000, TODAY), ("AAA", 10, 3_000_000, TODAY), ("CCC", 1, 1, TODAY))
    path = tmp_path / "out" / "liquid_symbols.csv"
    assert main(path, engine, TODAY) == 0
    assert read_symbols(path) == ["AAA", "BBB"]


def test_main_nobody_liquid_is_no_data(tmp_path: Path, engine: Engine) -> None:
    store(engine, ("AAA", 1, 1, TODAY))
    path = tmp_path / "liquid_symbols.csv"
    assert main(path, engine, TODAY) == NO_DATA
    assert NO_DATA == 4
    assert not path.exists()


def test_screen_drops_a_symbol_halted_today_even_with_a_high_average(engine: Engine) -> None:
    store(engine, *[("AAA", 20_000, 20_000, d) for d in days(19, YESTERDAY)], ("AAA", 20_000, 0, TODAY))  # avg 380 bn
    store(engine, ("BBB", 10, 3_000_000, TODAY))
    assert screen(engine, TODAY) == ["BBB"]


def test_main_removes_an_old_shortlist_when_nobody_is_liquid(tmp_path: Path, engine: Engine) -> None:
    path = tmp_path / "liquid_symbols.csv"
    path.write_text("code\nOLD\n", encoding="utf-8")
    store(engine, ("AAA", 1, 1, TODAY))
    assert main(path, engine, TODAY) == NO_DATA
    assert not path.exists()


def test_main_defaults_to_today_in_vietnam(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDatetime(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return dt.datetime(2026, 10, 23, 18, 0, tzinfo=dt.UTC).astimezone(tz)  # 25:00 in Vietnam: already the 24th

    monkeypatch.setattr(vn_stock_screen, "dt", SimpleNamespace(datetime=FakeDatetime))
    store(engine, ("AAA", 10, 3_000_000, dt.date(2026, 10, 24)))  # the Vietnam date, not the UTC one (23rd)
    assert main(tmp_path / "liquid_symbols.csv", engine) == 0


def test_screen_on_real_history(real_prices: Engine) -> None:
    """HPG trades ~395 billion VND a session on average, AAM ~0.02 billion: only HPG passes."""
    assert screen(real_prices, dt.date(2026, 10, 29)) == ["HPG"]


def test_run_as_script(tmp_path: Path, engine: Engine, pg_url: str) -> None:
    """The real entry point: argv, DATABASE_URL and the crash on a stale session (exit 1, not 4)."""
    store(engine, ("AAA", 10, 3_000_000, TODAY))
    env = {**os.environ, "DATABASE_URL": pg_url.replace("postgresql+psycopg://", "postgres://")}
    cmd = [sys.executable, "-m", "scripts.vn_stock_screen", str(tmp_path / "liquid_symbols.csv")]
    result = subprocess.run(cmd, capture_output=True, cwd=Path(__file__).parents[2], env=env)
    assert result.returncode == 1
    assert b"late or failed" in result.stderr
