from pathlib import Path
from unittest.mock import MagicMock

import pytest

from libs.analysis.models import AnalysisReport
from libs.constants import SESSION_MISMATCH
from libs.decision.candidates import read_input
from scripts.vn_stock_decision_filter import main
from tests.libs.decision.fakes import DAY, report, result, write_history


def setup(tmp_path: Path, analysis: AnalysisReport) -> tuple[Path, Path, Path]:
    """The two artifacts of the run (analysis JSON and history directory) and where the output goes."""
    analysis_json = tmp_path / "vn_stock_analysis.json"
    analysis_json.write_text(analysis.model_dump_json(), encoding="utf-8")
    history = tmp_path / "history"
    history.mkdir()
    for symbol in analysis.symbols:
        write_history(history, symbol.symbol)
    return analysis_json, history, tmp_path / "out" / "input.json"


def test_writes_the_candidates_of_the_session(tmp_path: Path) -> None:
    analysis_json, history, output = setup(tmp_path, report(result("HPG", 71.5), result("AAM", 39.9)))
    assert main(DAY.isoformat(), analysis_json, history, output) == 0
    data = read_input(output)
    assert data.session == DAY
    assert [candidate.symbol for candidate in data.symbols] == ["HPG"]


def test_a_session_that_is_not_the_reports_fails_and_leaves_no_older_output(tmp_path: Path) -> None:
    analysis_json, history, output = setup(tmp_path, report(result("HPG", 71.5)))
    output.parent.mkdir()
    output.write_text("an older input", encoding="utf-8")
    log = MagicMock()
    assert main("2026-11-11", analysis_json, history, output, log) == SESSION_MISMATCH
    assert not output.exists()
    log.error.assert_called_once()


def test_a_candidate_without_a_history_file_is_a_crash_not_a_quiet_exit(tmp_path: Path) -> None:
    analysis_json, history, output = setup(tmp_path, report(result("HPG", 71.5)))
    (history / "HPG.json").unlink()
    with pytest.raises(FileNotFoundError):
        main(DAY.isoformat(), analysis_json, history, output)
    assert not output.exists()


def test_a_session_that_is_not_a_date_is_a_crash(tmp_path: Path) -> None:
    analysis_json, history, output = setup(tmp_path, report(result("HPG", 71.5)))
    with pytest.raises(ValueError):
        main("yesterday", analysis_json, history, output)


def test_nobody_at_the_minimum_writes_an_empty_list(tmp_path: Path) -> None:
    analysis_json, history, output = setup(tmp_path, report(result("AAM", 12)))
    assert main(DAY.isoformat(), analysis_json, history, output) == 0
    assert read_input(output).symbols == []


def test_the_job_summary_shows_counts_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    analysis_json, history, output = setup(tmp_path, report(result("HPG", 71.5), result("AAM", 12)))
    main(DAY.isoformat(), analysis_json, history, output)
    text = summary.read_text(encoding="utf-8")
    assert "1 of 2 scored symbols at 40 or more" in text
    assert "HPG" not in text
