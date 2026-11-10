import datetime as dt
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from libs.analysis.models import AnalysisReport, SymbolStatus
from libs.constants import NO_DATA
from scripts.vn_stock_analyze import load_history, main, read_listed_dates
from tests.libs.analysis.fakes import make_rows


def write_history(directory: Path, symbol: str, count: int) -> None:
    rows = [row.model_dump(mode="json") for row in make_rows(symbol, count)]
    (directory / f"{symbol}.json").write_text(json.dumps(rows), encoding="utf-8")


def test_load_history_reads_one_file_per_symbol(tmp_path: Path) -> None:
    write_history(tmp_path, "BBB", 2)
    write_history(tmp_path, "AAA", 1)
    (tmp_path / "notes.txt").write_text("ignored")
    history = load_history(tmp_path)
    assert list(history) == ["AAA", "BBB"]
    assert [price.date for price in history["BBB"]] == [dt.date(2026, 11, 9), dt.date(2026, 11, 10)]


def test_read_listed_dates(tmp_path: Path) -> None:
    csv_path = tmp_path / "symbols.csv"
    csv_path.write_text("code,short_name,company_name,listed_date\nAAA,A,Công ty A,2016-11-25\n", encoding="utf-8")
    assert read_listed_dates(csv_path) == {"AAA": dt.date(2016, 11, 25)}
    assert "HPG" in read_listed_dates()  # the real universe file


def test_main_without_history_is_no_data_and_removes_an_older_output(tmp_path: Path) -> None:
    output = tmp_path / "analysis.json"
    output.write_text("old")
    log = MagicMock()
    assert main(tmp_path / "missing", output, log=log) == NO_DATA
    assert "nothing to analyse" in log.error.call_args.args[0]
    assert not output.exists()  # an older analysis must not pass for today's


def test_main_writes_the_report_and_the_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    write_history(history_dir, "HPG", 260)  # real symbols of data/hose_symbols.csv, synthetic prices
    write_history(history_dir, "AAM", 30)
    output, summary_file = tmp_path / "out" / "analysis.json", tmp_path / "summary.md"
    summary_file.write_text("earlier step\n")
    log = MagicMock()

    assert main(history_dir, output, summary_path=summary_file, log=log) == 0

    report = AnalysisReport.model_validate_json(output.read_text(encoding="utf-8"))  # the contract Phase 2 reads
    assert [(item.symbol, item.status) for item in report.symbols] == [
        ("HPG", SymbolStatus.SCORED),
        ("AAM", SymbolStatus.INSUFFICIENT_DATA),
    ]
    text = summary_file.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n## VN stock screening score")  # appended, never overwritten
    assert "| 1 | HPG |" in text
    assert log.info.call_args.args[1:5] == (dt.date(2026, 11, 10), 1, 1, 1)  # as_of, scored, insufficient, flagged


def test_main_without_a_summary_file_logs_the_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    write_history(tmp_path, "HPG", 30)
    log = MagicMock()
    assert main(tmp_path, tmp_path / "analysis.json", log=log) == 0
    assert "| 1 | HPG |" in log.info.call_args_list[0].args[1]


def test_main_uses_github_step_summary_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary_file = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    write_history(tmp_path, "HPG", 30)
    assert main(tmp_path, tmp_path / "analysis.json", log=MagicMock()) == 0
    assert "| 1 | HPG |" in summary_file.read_text(encoding="utf-8")
