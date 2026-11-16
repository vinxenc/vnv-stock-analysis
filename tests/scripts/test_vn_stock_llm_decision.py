import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from libs.decision.base import BaseDecider, Decision
from libs.decision.candidates import Candidate, build_input, write_input
from libs.decision.models import Decider, Verdict
from scripts.vn_stock_llm_decision import main
from tests.libs.decision.fakes import DAY, report, result, write_history

REASON = "Xu hướng tăng, dòng tiền vào."


def write_candidates(tmp_path: Path, *codes: str) -> Path:
    """The input JSON of the filter job with these symbols as candidates."""
    history = tmp_path / "history"
    history.mkdir(exist_ok=True)
    for code in codes:
        write_history(history, code)
    path = tmp_path / "input.json"
    write_input(build_input(report(*(result(code, 71.5) for code in codes)), history), path)
    return path


class FakeDecider(BaseDecider):
    """Answers the candidates with `answers` (decision, probability), in order; `error` is raised instead."""

    kind = Decider.LLM
    model_name = "fake/model"

    def __init__(self, *answers: tuple[Verdict, float], error: Exception | None = None) -> None:
        self.answers = answers
        self.error = error
        self.calls: list[tuple[dt.date, list[str]]] = []

    def decide_all(self, session: dt.date, candidates: list[Candidate]) -> dict[str, Decision]:
        self.calls.append((session, [candidate.symbol for candidate in candidates]))
        if self.error:
            raise self.error
        return {
            candidate.symbol: Decision(
                decision=decision, probability=probability, reason=REASON, input={"symbol": candidate.symbol}
            )
            for candidate, (decision, probability) in zip(candidates, self.answers, strict=True)
        }


def stored(engine: Engine) -> list[tuple]:
    columns = "date, symbol, model_name, decider, decision, probability, reason, input, hit, created_at IS NOT NULL"
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(f"SELECT {columns} FROM vn_stock_decisions ORDER BY 2"))]


def test_stores_one_row_per_candidate(tmp_path: Path, engine: Engine) -> None:
    decider = FakeDecider((Verdict.BUY, 0.62), (Verdict.SKIP, 0.2))
    assert main(write_candidates(tmp_path, "HPG", "FPT"), engine, decider) == 0
    assert decider.calls == [(DAY, ["HPG", "FPT"])]  # the report's order
    assert stored(engine) == [
        (DAY, "FPT", "fake/model", "llm", "skip", 0.2, REASON, {"symbol": "FPT"}, None, True),
        (DAY, "HPG", "fake/model", "llm", "buy", 0.62, REASON, {"symbol": "HPG"}, None, True),
    ]


def test_no_candidate_asks_nobody_and_stores_nothing(tmp_path: Path, engine: Engine) -> None:
    decider = FakeDecider()
    assert main(write_candidates(tmp_path), engine, decider) == 0
    assert decider.calls == []
    assert stored(engine) == []


def test_a_rerun_upserts(tmp_path: Path, engine: Engine) -> None:
    main(write_candidates(tmp_path, "HPG", "FPT"), engine, FakeDecider((Verdict.BUY, 0.62), (Verdict.BUY, 0.7)))
    with engine.begin() as connection:  # as if the outcome job and a day had passed
        connection.execute(text("UPDATE vn_stock_decisions SET hit = true, return_5 = 0.05, created_at = '2026-01-01'"))
    main(write_candidates(tmp_path, "HPG"), None, FakeDecider((Verdict.SKIP, 0.3)))  # no engine: $DATABASE_URL's
    columns = "symbol, decision, probability, hit, return_5, created_at > '2026-01-02'"
    with engine.connect() as connection:
        rows = [tuple(row) for row in connection.execute(text(f"SELECT {columns} FROM vn_stock_decisions ORDER BY 1"))]
    assert rows == [
        ("FPT", "buy", 0.7, True, 0.05, False),  # not answered again: its older row stays as it was
        ("HPG", "skip", 0.3, None, None, True),  # answered again: new answer, new created_at, outcome emptied
    ]


def test_a_failing_decider_crashes_and_stores_nothing(tmp_path: Path, engine: Engine) -> None:
    with pytest.raises(RuntimeError, match="no answer"):
        main(write_candidates(tmp_path, "HPG"), engine, FakeDecider(error=RuntimeError("no answer")))
    assert stored(engine) == []


def test_the_default_decider_is_the_llm_on_openrouter(
    tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert main(write_candidates(tmp_path), engine) == 0  # no candidate: nothing is called
    assert "0 symbols decided by anthropic/claude-opus-5.5, 0 buy" in summary.read_text(encoding="utf-8")


def test_the_job_summary_shows_counts_only(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    main(write_candidates(tmp_path, "HPG", "FPT"), engine, FakeDecider((Verdict.BUY, 0.62), (Verdict.SKIP, 0.2)))
    written = summary.read_text(encoding="utf-8")
    assert "2 symbols decided by fake/model, 1 buy" in written
    assert "HPG" not in written


def test_a_failed_insert_does_not_print_the_decisions(tmp_path: Path, engine: Engine) -> None:
    with engine.begin() as connection:  # a CHECK no row can pass: the INSERT of the script fails
        connection.execute(text("ALTER TABLE vn_stock_decisions ADD CONSTRAINT ck_refuse_all CHECK (false) NOT VALID"))
    try:
        with pytest.raises(RuntimeError, match="CheckViolation 23514") as error:
            main(write_candidates(tmp_path, "HPG"), engine, FakeDecider((Verdict.BUY, 0.62)))
    finally:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE vn_stock_decisions DROP CONSTRAINT ck_refuse_all"))
    assert "Xu hướng" not in str(error.value)
    assert error.value.__suppress_context__  # the traceback does not show the database error with the failing row
