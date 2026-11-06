import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from sqlalchemy import Engine
from sqlmodel import Session

from libs.constants import NO_DATA
from libs.db.models import Price
from scripts.vn_stock_get_history import SESSIONS, get_history, main

END = dt.date(2026, 10, 23)


def store(engine: Engine, symbol: str, count: int, end: dt.date = END) -> None:
    """`count` consecutive daily rows of `symbol` ending on `end`; close is the day offset so order is checkable."""
    with Session(engine) as session:
        for i in range(count):
            price = float(i + 1)
            row = dict(symbol=symbol, source="A", date=end - dt.timedelta(days=count - 1 - i), volume=i)
            session.add(Price.model_validate(dict(open=price, high=price, low=price, close=price, **row)))
        session.commit()


def test_get_history_keeps_the_last_sessions_in_ascending_date_order(engine: Engine) -> None:
    assert SESSIONS == 260
    store(engine, "AAA", SESSIONS + 5)
    store(engine, "BBB", 3)  # another symbol: never mixed in
    with Session(engine) as session:
        rows = get_history(session, "AAA")
    assert len(rows) == SESSIONS
    assert {row.symbol for row in rows} == {"AAA"}
    assert rows[-1].date == END
    assert rows[0].date == END - dt.timedelta(days=SESSIONS - 1)  # the 5 oldest rows are cut
    assert [row.date for row in rows] == sorted(row.date for row in rows)


def read(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_main_writes_one_json_per_symbol_and_logs_the_short_ones(tmp_path: Path, engine: Engine) -> None:
    csv, output = tmp_path / "liquid_symbols.csv", tmp_path / "out" / "vn_stock_history"
    csv.write_text("code\nAAA\nBBB\nZZZ\n", encoding="utf-8")
    store(engine, "AAA", SESSIONS)
    store(engine, "BBB", 2)
    log = MagicMock()
    assert main(csv, output, engine, log) == 0
    assert sorted(path.name for path in output.iterdir()) == ["AAA.json", "BBB.json"]  # ZZZ has no row, no file
    assert len(read(output / "AAA.json")) == SESSIONS
    assert [(row["symbol"], row["date"], row["close"]) for row in read(output / "BBB.json")] == [
        ("BBB", "2026-10-22", 1.0),
        ("BBB", "2026-10-23", 2.0),
    ]
    assert {"open", "high", "low", "volume", "source"} <= read(output / "BBB.json")[0].keys()
    warning = log.warning.call_args.args[2]
    assert "BBB=2" in warning and "ZZZ=0" in warning and "AAA" not in warning


def test_main_empties_the_output_directory_first(tmp_path: Path, engine: Engine) -> None:
    csv, output = tmp_path / "liquid_symbols.csv", tmp_path / "vn_stock_history"
    csv.write_text("code\nAAA\n", encoding="utf-8")
    output.mkdir()
    (output / "OLD.json").write_text("[]", encoding="utf-8")
    store(engine, "AAA", 1)
    assert main(csv, output, engine) == 0
    assert [path.name for path in output.iterdir()] == ["AAA.json"]


def test_main_removes_an_old_history_when_nothing_is_found(tmp_path: Path, engine: Engine) -> None:
    csv, output = tmp_path / "liquid_symbols.csv", tmp_path / "vn_stock_history"
    csv.write_text("code\nAAA\n", encoding="utf-8")
    output.mkdir()
    (output / "OLD.json").write_text("[]", encoding="utf-8")
    assert main(csv, output, engine) == NO_DATA
    assert NO_DATA == 4
    assert not output.exists()


def test_run_as_script(tmp_path: Path, engine: Engine, pg_url: str) -> None:
    """The real entry point: argv and DATABASE_URL."""
    csv, output = tmp_path / "liquid_symbols.csv", tmp_path / "vn_stock_history"
    csv.write_text("code\nAAA\n", encoding="utf-8")
    store(engine, "AAA", 1)
    env = {**os.environ, "DATABASE_URL": pg_url.replace("postgresql+psycopg://", "postgres://")}
    cmd = [sys.executable, "-m", "scripts.vn_stock_get_history", str(csv), str(output)]
    assert subprocess.run(cmd, capture_output=True, cwd=Path(__file__).parents[2], env=env).returncode == 0
    assert len(read(output / "AAA.json")) == 1
