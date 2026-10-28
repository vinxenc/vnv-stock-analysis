import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlmodel import Session, select

from libs.db.models import Price
from scripts.vn_stock_daily_price_store import NO_DATA, main, read_prices


def row(symbol: str, close: float = 2.0, date: str = "2026-10-23", source: str = "A") -> dict[str, object]:
    return dict(symbol=symbol, source=source, date=date, open=1, high=3, low=1, close=close, volume=3_000_000_000)


def write_json(path: Path, *rows: dict[str, object]) -> Path:
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def stored(engine: Engine) -> list[Price]:
    with Session(engine) as session:
        return list(session.exec(select(Price).order_by(Price.symbol, Price.date)))


def test_read_prices_validates(tmp_path: Path) -> None:
    assert [price.symbol for price in read_prices(write_json(tmp_path / "p.json", row("AAA"), row("BBB")))] == [
        "AAA",
        "BBB",
    ]
    with pytest.raises(ValidationError):
        read_prices(write_json(tmp_path / "bad.json", row("AAA", close=-1)))


def test_main_inserts_rows(tmp_path: Path, engine: Engine) -> None:
    assert main(write_json(tmp_path / "p.json", row("AAA"), row("BBB", close=5)), engine) == 0
    rows = stored(engine)
    assert [(price.symbol, price.close) for price in rows] == [("AAA", 2.0), ("BBB", 5.0)]
    assert rows[0].volume == 3_000_000_000  # BIGINT, not INT


def test_main_twice_overwrites_same_symbol_and_date(tmp_path: Path, engine: Engine) -> None:
    main(write_json(tmp_path / "1.json", row("AAA", close=2), row("BBB")), engine)
    main(write_json(tmp_path / "2.json", row("AAA", close=9, source="B"), row("AAA", date="2026-10-24")), engine)
    assert [(price.symbol, str(price.date), price.close, price.source) for price in stored(engine)] == [
        ("AAA", "2026-10-23", 9.0, "B"),
        ("AAA", "2026-10-24", 2.0, "A"),
        ("BBB", "2026-10-23", 2.0, "A"),
    ]


def test_main_bad_row_stores_nothing(tmp_path: Path, engine: Engine) -> None:
    with pytest.raises(ValidationError):
        main(write_json(tmp_path / "p.json", row("AAA"), row("BBB", close=0)), engine)
    assert stored(engine) == []


def test_main_empty_file_is_no_data(tmp_path: Path, engine: Engine) -> None:
    assert main(write_json(tmp_path / "p.json"), engine) == NO_DATA
    assert NO_DATA == 4
    assert stored(engine) == []


def test_run_as_script(tmp_path: Path, engine: Engine, pg_url: str) -> None:
    """The real entry point: argv, DATABASE_URL (postgres:// style) and exit code."""
    path = write_json(tmp_path / "p.json", row("AAA"))
    env = {**os.environ, "DATABASE_URL": pg_url.replace("postgresql+psycopg://", "postgres://")}
    cmd = [sys.executable, "-m", "scripts.vn_stock_daily_price_store", str(path)]
    result = subprocess.run(cmd, capture_output=True, cwd=Path(__file__).parents[2], env=env)
    assert result.returncode == 0, result.stderr
    assert [price.symbol for price in stored(engine)] == ["AAA"]


def test_crash_is_not_no_data(tmp_path: Path) -> None:
    cmd = [sys.executable, "-m", "scripts.vn_stock_daily_price_store", str(tmp_path / "missing.json")]
    result = subprocess.run(cmd, capture_output=True, cwd=Path(__file__).parents[2])
    assert result.returncode == 1
    assert b"FileNotFoundError" in result.stderr
