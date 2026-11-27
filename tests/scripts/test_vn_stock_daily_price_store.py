import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlmodel import Session, select

from libs.db.models import Price, PriceAdjustment
from scripts.vn_stock_daily_price_store import MAX_ADJUSTED, NO_DATA, main, read_prices


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


def test_read_prices_dedupes_same_symbol_and_date_last_wins(tmp_path: Path, engine: Engine) -> None:
    path = write_json(tmp_path / "p.json", row("AAA", close=2), row("BBB"), row("AAA", close=7))
    assert [(price.symbol, price.close) for price in read_prices(path)] == [("AAA", 7.0), ("BBB", 2.0)]
    assert main(path, engine) == 0  # a duplicate key would make Postgres reject the whole statement
    assert [(price.symbol, price.close) for price in stored(engine)] == [("AAA", 7.0), ("BBB", 2.0)]


def test_main_inserts_rows(tmp_path: Path, engine: Engine) -> None:
    assert main(write_json(tmp_path / "p.json", row("AAA"), row("BBB", close=5)), engine) == 0
    rows = stored(engine)
    assert [(price.symbol, price.close) for price in rows] == [("AAA", 2.0), ("BBB", 5.0)]
    assert rows[0].volume == 3_000_000_000  # BIGINT, not INT


def test_main_twice_overwrites_same_symbol_and_date(tmp_path: Path, engine: Engine) -> None:
    main(write_json(tmp_path / "1.json", row("AAA", close=2), row("BBB")), engine)
    main(write_json(tmp_path / "2.json", row("AAA", close=9, source="B")), engine)
    assert [(price.symbol, str(price.date), price.close, price.source) for price in stored(engine)] == [
        ("AAA", "2026-10-23", 9.0, "B"),
        ("BBB", "2026-10-23", 2.0, "A"),
    ]


def test_only_the_newest_bar_of_a_symbol_is_stored(tmp_path: Path, engine: Engine) -> None:
    """The older bars of the file are evidence for an adjustment, never stored as such."""
    main(write_json(tmp_path / "p.json", row("AAA", date="2026-10-22"), row("AAA", date="2026-10-23")), engine)
    assert [str(price.date) for price in stored(engine)] == ["2026-10-23"]


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


# Dividend adjustments (libs/prices/adjustment.py)
DAYS = ["2026-11-19", "2026-11-20", "2026-11-21", "2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27"]


def ohlc(symbol: str, date: str, close: float, factor: float = 1.0, volume: int = 1000) -> dict[str, object]:
    prices = {name: round(close * scale * factor, 2) for name, scale in (("open", 1.01), ("high", 1.02), ("low", 0.98))}
    return dict(symbol=symbol, source="DNSE", date=date, close=round(close * factor, 2), volume=volume, **prices)


def adjustments(engine: Engine) -> list[tuple]:
    with Session(engine) as session:
        return [
            (a.symbol, str(a.through), round(a.factor, 4), a.source, a.bars)
            for a in session.exec(select(PriceAdjustment))
        ]


def test_the_real_bvh_case_is_repaired(tmp_path: Path, engine: Engine) -> None:
    """2026-11-25 was re-stored adjusted (56.9 -> 56.09) after midnight, the older bars are raw; the next sync's window
    shows them all adjusted by 0.9858, so they are multiplied and 2026-11-25 is left as it is."""
    raw = [58.0, 57.6, 57.9, 57.2]
    for day, close in zip(DAYS, raw, strict=False):
        main(write_json(tmp_path / f"{day}.json", ohlc("BVH", day, close)), engine)
    bvh_25 = dict(
        symbol="BVH", source="DNSE", date=DAYS[4], open=57.18, high=57.67, low=56.09, close=56.09, volume=302300
    )
    main(write_json(tmp_path / "25.json", bvh_25), engine)
    window = [ohlc("BVH", day, close, factor=0.98576) for day, close in zip(DAYS, raw, strict=False)]
    window += [bvh_25, ohlc("BVH", DAYS[5], 54.0)]
    assert main(write_json(tmp_path / "w.json", *window), engine) == 0
    assert adjustments(engine) == [("BVH", DAYS[3], 0.9858, "DNSE", 4)]
    assert [price.close for price in stored(engine)] == [row["close"] for row in window]
    assert main(write_json(tmp_path / "w.json", *window), engine) == 0  # a rerun changes nothing, logs nothing
    assert len(adjustments(engine)) == 1


def test_older_bars_outside_the_window_are_multiplied(tmp_path: Path, engine: Engine) -> None:
    for day in DAYS[:5]:
        main(write_json(tmp_path / f"{day}.json", ohlc("FPT", day, 44.5)), engine)
    window = [ohlc("FPT", day, 44.5, factor=0.9775) for day in DAYS[3:5]] + [ohlc("FPT", DAYS[5], 43.0)]
    main(write_json(tmp_path / "w.json", *window), engine)
    closes = [price.close for price in stored(engine)]
    assert closes[:3] == [pytest.approx(44.5 * 0.9775, abs=0.005)] * 3  # not returned by the source: times the factor
    assert closes[3:] == [43.5, 43.5, 43.0]  # the source's own bars, then the new one
    assert adjustments(engine)[0][1:] == (DAYS[4], 0.9775, "DNSE", 5)


def test_a_cheap_symbol_does_not_drift(tmp_path: Path, engine: Engine) -> None:
    """At 1.5 a 0.01 step is 0.7%: the window bars take the source's values, so the next run sees no move."""
    for day in DAYS[:4]:
        main(write_json(tmp_path / f"{day}.json", ohlc("PEN", day, 1.52)), engine)
    first = [ohlc("PEN", day, 1.52, factor=0.9) for day in DAYS[:4]] + [ohlc("PEN", DAYS[4], 1.4)]
    main(write_json(tmp_path / "1.json", *first), engine)
    second = first[1:] + [ohlc("PEN", DAYS[5], 1.41)]
    main(write_json(tmp_path / "2.json", *second), engine)
    assert len(adjustments(engine)) == 1
    assert [price.close for price in stored(engine)] == [1.37, 1.37, 1.37, 1.37, 1.4, 1.41]


def test_bars_that_moved_otherwise_are_left_alone(tmp_path: Path, engine: Engine) -> None:
    for day in DAYS[:3]:
        main(write_json(tmp_path / f"{day}.json", ohlc("MSH", day, 34.6)), engine)
    window = [ohlc("MSH", DAYS[0], 34.6), ohlc("MSH", DAYS[1], 34.6, factor=0.88), ohlc("MSH", DAYS[2], 34.6)]
    log = FakeLog()
    assert main(write_json(tmp_path / "w.json", *window, ohlc("MSH", DAYS[3], 30.0)), engine, log) == 0
    assert adjustments(engine) == []
    assert [price.close for price in stored(engine)] == [34.6, 34.6, 34.6, 30.0]
    assert any("not adjusted: MSH" in line for line in log.lines)


def test_too_many_adjustments_store_nothing(tmp_path: Path, engine: Engine) -> None:
    symbols = [f"S{n:02}" for n in range(MAX_ADJUSTED + 1)]
    main(write_json(tmp_path / "0.json", *[ohlc(symbol, DAYS[0], 10.0) for symbol in symbols]), engine)
    window = [row for s in symbols for row in (ohlc(s, DAYS[0], 10.0, factor=0.9), ohlc(s, DAYS[1], 9.0))]
    with pytest.raises(RuntimeError, match="stored nothing"):
        main(write_json(tmp_path / "w.json", *window), engine)
    assert {price.close for price in stored(engine)} == {10.0} and adjustments(engine) == []


class FakeLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def debug(self, msg: str, *args: object) -> None:
        self.lines.append(msg % args)

    info = warning = error = debug
