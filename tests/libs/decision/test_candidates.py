import datetime as dt
from pathlib import Path

import pytest

from libs.decision.candidates import BARS, MIN_SCORE, DecisionInput, build_input, read_input, write_input
from tests.libs.decision.fakes import DAY, report, result, write_history


def symbols(data: DecisionInput) -> list[str]:
    return [candidate.symbol for candidate in data.symbols]


def test_keeps_the_symbols_from_the_minimum_score_up_in_the_reports_order(tmp_path: Path) -> None:
    """Exactly the minimum is in, just under it is out, and so is a symbol without a score (insufficient data)."""
    assert MIN_SCORE == 40
    rows = [("FPT", 85), ("HPG", MIN_SCORE), ("AAM", 39.9), ("VCB", None), ("SSI", 61.5)]
    for code, _ in rows:
        write_history(tmp_path, code)
    data = build_input(report(*(result(code, score) for code, score in rows)), tmp_path)
    assert data.session == DAY
    assert symbols(data) == ["FPT", "HPG", "SSI"]
    assert data.symbols[0].score == 85
    assert data.symbols[0].indicators[0].raw == {"close_vs_sma20": 0.02}


def test_gives_each_candidate_its_last_bars_ascending_without_the_source_columns(tmp_path: Path) -> None:
    write_history(tmp_path, "HPG", count=BARS + 10)
    bars = build_input(report(result("HPG", 70)), tmp_path).symbols[0].bars
    assert len(bars) == BARS
    assert [bar.date for bar in bars] == sorted(bar.date for bar in bars)
    assert bars[-1].date == DAY
    assert set(bars[0].model_dump()) == {"date", "open", "high", "low", "close", "volume"}


def test_never_gives_a_bar_after_the_session(tmp_path: Path) -> None:
    """A history that runs on past the session (a sync stored newer bars) is cut at it."""
    write_history(tmp_path, "HPG", count=70, end=DAY + dt.timedelta(days=3))
    bars = build_input(report(result("HPG", 70)), tmp_path).symbols[0].bars
    assert bars[-1].date == DAY
    assert len(bars) == BARS


def test_a_short_history_gives_all_its_bars(tmp_path: Path) -> None:
    write_history(tmp_path, "HPG", count=10)
    assert len(build_input(report(result("HPG", 70)), tmp_path).symbols[0].bars) == 10


def test_a_candidate_without_a_history_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_input(report(result("HPG", 70)), tmp_path)


def test_nobody_at_the_minimum_gives_an_empty_list(tmp_path: Path) -> None:
    data = build_input(report(result("AAM", 12), result("VCB", None)), tmp_path)
    assert (data.session, data.symbols) == (DAY, [])


def test_the_file_round_trips(tmp_path: Path) -> None:
    write_history(tmp_path, "HPG")
    data = build_input(report(result("HPG", 70)), tmp_path)
    path = tmp_path / "out" / "input.json"
    write_input(data, path)
    assert read_input(path) == data
