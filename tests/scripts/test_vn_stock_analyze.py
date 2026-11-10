import datetime as dt
import json
from pathlib import Path
from unittest.mock import MagicMock

from libs.constants import NO_DATA
from scripts.vn_stock_analyze import load_history, main


def write_history(directory: Path, symbol: str, *dates: dt.date) -> None:
    rows = [
        dict(symbol=symbol, source="A", date=date.isoformat(), open=1, high=1, low=1, close=1, volume=1)
        for date in dates
    ]
    (directory / f"{symbol}.json").write_text(json.dumps(rows), encoding="utf-8")


def test_load_history_reads_one_file_per_symbol(tmp_path: Path) -> None:
    write_history(tmp_path, "BBB", dt.date(2026, 11, 9), dt.date(2026, 11, 10))
    write_history(tmp_path, "AAA", dt.date(2026, 11, 10))
    (tmp_path / "notes.txt").write_text("ignored")
    history = load_history(tmp_path)
    assert list(history) == ["AAA", "BBB"]
    assert [price.date for price in history["BBB"]] == [dt.date(2026, 11, 9), dt.date(2026, 11, 10)]


def test_main_without_history_is_no_data(tmp_path: Path) -> None:
    log = MagicMock()
    assert main(tmp_path, log) == NO_DATA
    assert "nothing to analyse" in log.error.call_args.args[0]
    assert main(tmp_path / "missing", log) == NO_DATA


def test_main_logs_the_session_analysed(tmp_path: Path) -> None:
    write_history(tmp_path, "AAA", dt.date(2026, 11, 9), dt.date(2026, 11, 10))
    write_history(tmp_path, "BBB", dt.date(2026, 11, 10))
    log = MagicMock()
    assert main(tmp_path, log) == 0
    assert log.info.call_args.args[1:] == (dt.date(2026, 11, 10), 2)
