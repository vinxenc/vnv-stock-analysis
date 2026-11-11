import datetime as dt
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from libs.analysis import scoring
from libs.analysis.models import (
    AnalysisReport,
    Flag,
    IndicatorResult,
    IndicatorStatus,
    SymbolResult,
    Theme,
    Timeframe,
)
from libs.constants import NO_DATA
from libs.db.models import Ranking
from scripts.vn_stock_analyze import load_history, main, read_listed_dates, store
from tests.libs.analysis.fakes import make_rows

DAY = dt.date(2026, 11, 10)


def result(code: str, score: float | None, flags: list[Flag] | None = None) -> SymbolResult:
    """A scored symbol with one indicator, enough to check what is stored."""
    indicator = IndicatorResult(
        id=1, theme=Theme.TREND, status=IndicatorStatus.SCORED, points=2.5, max_points=3, raw={"close_vs_sma20": 0.02}
    )
    themes = {theme: 2.5 if theme == Theme.TREND else 0.0 for theme in Theme}
    return SymbolResult(
        symbol=code, score=score, coverage=80, turnover=1e6, themes=themes, indicators=[indicator], flags=flags or []
    )


def report(*symbols: SymbolResult, timeframe: Timeframe = Timeframe.DAILY) -> AnalysisReport:
    """A report of DAY with these symbols, in this order."""
    return AnalysisReport(as_of=DAY, timeframe=timeframe, universe_size=406, sources=["DNSE"], symbols=list(symbols))


def rankings(engine: Engine) -> list[Ranking]:
    """Every stored row, by date, timeframe and symbol."""
    with Session(engine) as session:
        return list(session.exec(select(Ranking).order_by(Ranking.date, Ranking.timeframe, Ranking.symbol)))


def test_store_writes_one_row_per_scored_symbol_with_the_weights(engine: Engine) -> None:
    """Insufficient data (null) and 0 points are skipped; the JSONB columns round-trip; each row carries the weights."""
    store(report(result("HPG", 71.5, [Flag.CEILING_LOCKED]), result("AAM", None), result("VCB", 0)), engine)
    rows = rankings(engine)
    assert [(row.date, row.timeframe, row.symbol, row.score) for row in rows] == [(DAY, Timeframe.DAILY, "HPG", 71.5)]
    hpg = rows[0]
    assert hpg.flags == ["ceiling_locked"]
    assert hpg.themes["trend"] == 2.5
    assert hpg.indicators[0]["raw"] == {"close_vs_sma20": 0.02}
    assert hpg.meta == scoring.metadata()
    assert sum(weight["max_points"] for weight in hpg.meta["weights"]) == 100


def test_store_upserts_on_date_timeframe_and_symbol(engine: Engine) -> None:
    """A rerun of the session overwrites the symbols it scores again; one that left the shortlist keeps its older row,
    and the other timeframes of that date are untouched."""
    store(report(result("HPG", 70), result("AAM", 60)), engine)
    store(report(result("HPG", 50), timeframe=Timeframe.WEEKLY), engine)
    store(report(result("VCB", 80), result("HPG", 65)), engine)
    assert [(row.timeframe, row.symbol, row.score) for row in rankings(engine)] == [
        (Timeframe.DAILY, "AAM", 60),  # stale: not in the rerun
        (Timeframe.DAILY, "HPG", 65),
        (Timeframe.DAILY, "VCB", 80),
        (Timeframe.WEEKLY, "HPG", 50),
    ]


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


def test_main_writes_the_report_the_summary_and_the_ranking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    write_history(history_dir, "HPG", 260)  # real symbols of data/hose_symbols.csv, synthetic prices
    write_history(history_dir, "AAM", 30)
    output, summary_file = tmp_path / "out" / "analysis.json", tmp_path / "summary.md"
    summary_file.write_text("earlier step\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    log = MagicMock()

    assert main(history_dir, output, engine, log=log) == 0

    report = AnalysisReport.model_validate_json(output.read_text(encoding="utf-8"))  # the contract Phase 2 reads
    assert [(item.symbol, item.score is not None) for item in report.symbols] == [("HPG", True), ("AAM", False)]
    text = summary_file.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n## VN stock screening score")  # appended, never overwritten
    assert "| 1 | HPG |" in text
    assert log.info.call_args.args[1:4] == (dt.date(2026, 11, 10), 2, 1)  # as_of, symbols, scored
    assert [row.symbol for row in rankings(engine)] == ["HPG"]  # AAM has no score: not stored


def test_main_without_a_summary_file_logs_the_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    write_history(tmp_path, "HPG", 30)
    log = MagicMock()
    assert main(tmp_path, tmp_path / "analysis.json", engine, log=log) == 0
    assert "| 1 | HPG |" in log.info.call_args_list[0].args[1]


def test_real_hpg_and_aam_history_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Engine) -> None:
    """Real DNSE history (31-33 sessions): HPG is very liquid, AAM almost untraded and locked on its last two days.

    Neither has the 61 rows a score needs, so both are `insufficient data`: the ranking falls back on turnover.
    """
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    rows = json.loads((Path(__file__).parents[1] / "data" / "prices_hpg_aam.json").read_text(encoding="utf-8"))
    for symbol in ("HPG", "AAM"):
        symbol_rows = sorted((row for row in rows if row["symbol"] == symbol), key=lambda row: row["date"])
        (tmp_path / f"{symbol}.json").write_text(json.dumps(symbol_rows), encoding="utf-8")
    output = tmp_path / "analysis.json"

    assert main(tmp_path, output, engine, log=MagicMock()) == 0

    report = AnalysisReport.model_validate_json(output.read_text(encoding="utf-8"))
    hpg, aam = report.symbols
    assert (hpg.symbol, aam.symbol) == ("HPG", "AAM")  # no score for either: the more liquid one comes first
    assert hpg.score is None and aam.score is None and hpg.turnover > 1000 * aam.turnover
    close_location = {symbol.symbol: next(i for i in symbol.indicators if i.id == 15) for symbol in report.symbols}
    assert close_location["HPG"].status == IndicatorStatus.SCORED
    assert close_location["AAM"].status == IndicatorStatus.UNAVAILABLE  # high == low on the last session
    assert all(item.status == IndicatorStatus.UNAVAILABLE for item in aam.indicators if item.id in (5, 7, 17, 24))
    assert rankings(engine) == []  # neither has a score: nothing stored, nothing sent
