import datetime as dt
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from libs.analysis.models import AnalysisReport, IndicatorStatus
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
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    log = MagicMock()

    assert main(history_dir, output, log=log) == 0

    report = AnalysisReport.model_validate_json(output.read_text(encoding="utf-8"))  # the contract Phase 2 reads
    assert [(item.symbol, item.score is not None) for item in report.symbols] == [("HPG", True), ("AAM", False)]
    text = summary_file.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n## VN stock screening score")  # appended, never overwritten
    assert "| 1 | HPG |" in text
    assert log.info.call_args.args[1:4] == (dt.date(2026, 11, 10), 2, 1)  # as_of, symbols, scored


def test_main_without_a_summary_file_logs_the_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    write_history(tmp_path, "HPG", 30)
    log = MagicMock()
    assert main(tmp_path, tmp_path / "analysis.json", log=log) == 0
    assert "| 1 | HPG |" in log.info.call_args_list[0].args[1]


def test_real_hpg_and_aam_history_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real DNSE history (31-33 sessions): HPG is very liquid, AAM almost untraded and locked on its last two days.

    Neither has the 61 rows a score needs, so both are `insufficient data`: the ranking falls back on turnover.
    """
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    rows = json.loads((Path(__file__).parents[1] / "data" / "prices_hpg_aam.json").read_text(encoding="utf-8"))
    for symbol in ("HPG", "AAM"):
        symbol_rows = sorted((row for row in rows if row["symbol"] == symbol), key=lambda row: row["date"])
        (tmp_path / f"{symbol}.json").write_text(json.dumps(symbol_rows), encoding="utf-8")
    output = tmp_path / "analysis.json"

    assert main(tmp_path, output, log=MagicMock()) == 0

    report = AnalysisReport.model_validate_json(output.read_text(encoding="utf-8"))
    hpg, aam = report.symbols
    assert (hpg.symbol, aam.symbol) == ("HPG", "AAM")  # no score for either: the more liquid one comes first
    assert hpg.score is None and aam.score is None and hpg.turnover > 1000 * aam.turnover
    close_location = {symbol.symbol: next(i for i in symbol.indicators if i.id == 15) for symbol in report.symbols}
    assert close_location["HPG"].status == IndicatorStatus.SCORED
    assert close_location["AAM"].status == IndicatorStatus.UNAVAILABLE  # high == low on the last session
    assert all(item.status == IndicatorStatus.UNAVAILABLE for item in aam.indicators if item.id in (5, 7, 17, 24))
