import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from libs.db.models import ScreenHistory
from scripts.vn_stock_screen_done import main

DAY = dt.date(2026, 10, 23)


def history(engine: Engine) -> list[dt.date]:
    with Session(engine) as session:
        return [row.date for row in session.exec(select(ScreenHistory))]


def test_main_records_the_session_once_even_when_run_twice(tmp_path: Path, engine: Engine) -> None:
    """Two overlapping runs screened the same session: the second recording is not an error."""
    path = tmp_path / "screen_session.txt"
    path.write_text(DAY.isoformat(), encoding="utf-8")
    assert main(path, engine) == 0
    assert main(path, engine) == 0
    assert history(engine) == [DAY]


def test_run_as_script(tmp_path: Path, engine: Engine, pg_url: str) -> None:
    """The real entry point: argv and DATABASE_URL."""
    path = tmp_path / "screen_session.txt"
    path.write_text(DAY.isoformat(), encoding="utf-8")
    env = {**os.environ, "DATABASE_URL": pg_url.replace("postgresql+psycopg://", "postgres://")}
    cmd = [sys.executable, "-m", "scripts.vn_stock_screen_done", str(path)]
    assert subprocess.run(cmd, capture_output=True, cwd=Path(__file__).parents[2], env=env).returncode == 0
    assert history(engine) == [DAY]
