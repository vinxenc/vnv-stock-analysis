import datetime as dt

import pytest

from libs.analysis.models import Flag, SymbolResult, SymbolStatus, Theme
from libs.analysis.report import build_report, rank
from libs.indicators import TalibIndicators
from tests.libs.analysis.fakes import make_rows

OLD = dt.date(2016, 1, 1)


def result(symbol: str, score: float | None, turnover: float) -> SymbolResult:
    status = SymbolStatus.SCORED if score is not None else SymbolStatus.INSUFFICIENT_DATA
    return SymbolResult(
        symbol=symbol, status=status, score=score, coverage=100, turnover=turnover, themes={}, indicators=[]
    )


def test_rank_by_score_then_turnover_with_unscored_symbols_last() -> None:
    ranked = rank(
        [
            result("NOSCORE_BIG", None, 900),
            result("LOW", 40, 500),
            result("TIE_SMALL", 70, 100),
            result("TIE_BIG", 70, 200),
            result("NOSCORE_SMALL", None, 5),
            result("TOP", 90, 1),
        ]
    )
    assert [item.symbol for item in ranked] == ["TOP", "TIE_BIG", "TIE_SMALL", "LOW", "NOSCORE_BIG", "NOSCORE_SMALL"]


def test_build_report_scores_ranks_and_counts() -> None:
    history = {"SHORT": make_rows("SHORT", 30), "UP": make_rows("UP", 260), "ONE": make_rows("ONE", 1)}
    listed = {"UP": OLD, "SHORT": dt.date(2026, 10, 1), "ONE": OLD, "NOT_SHORTLISTED": OLD}
    report = build_report(history, listed, TalibIndicators())

    assert report.as_of == dt.date(2026, 11, 10)
    assert report.universe_size == 4  # the symbols of data/hose_symbols.csv, not only the shortlist
    assert (report.scored, report.insufficient_data, report.flagged) == (1, 2, 2)  # SHORT and ONE
    assert report.sources == ["A"]
    assert [item.symbol for item in report.symbols][0] == "UP"  # the only scored symbol comes first

    up = report.symbols[0]
    assert up.status == SymbolStatus.SCORED and up.coverage == 100 and up.flags == []
    assert up.score == pytest.approx(sum(indicator.points for indicator in up.indicators), abs=0.01)
    assert up.score == pytest.approx(sum(up.themes.values()), abs=0.03)
    assert set(up.themes) == set(Theme)
    assert len(up.indicators) == 24
    # turnover = average close x volume of the last 20 sessions
    rows = history["UP"][-20:]
    assert up.turnover == pytest.approx(sum(row.close * row.volume for row in rows) / 20)

    short = next(item for item in report.symbols if item.symbol == "SHORT")
    assert short.status == SymbolStatus.INSUFFICIENT_DATA and short.score is None
    assert Flag.NEW_LISTING in short.flags and Flag.LOW_COVERAGE in short.flags
    one = next(item for item in report.symbols if item.symbol == "ONE")  # one row: no previous close, no crash
    assert one.status == SymbolStatus.INSUFFICIENT_DATA and one.flags == [Flag.LOW_COVERAGE]


def test_sources_are_the_ones_of_the_session_analysed() -> None:
    history = {"AAA": make_rows("AAA", 30, source="DNSE"), "BBB": make_rows("BBB", 30, source="VNDirect")}
    report = build_report(history, {"AAA": OLD, "BBB": OLD}, TalibIndicators())
    assert report.sources == ["DNSE", "VNDirect"]
