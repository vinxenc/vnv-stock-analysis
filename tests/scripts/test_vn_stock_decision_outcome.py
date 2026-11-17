from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from scripts.vn_stock_decision_outcome import main
from tests.libs.decision.test_outcome import S, bars, decide, path


def test_reports_the_counts(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    bars(engine, "HPG", path(20.0, 20.0, 20.0, 20.0, 20.0, 21.0, 21.0, 21.0))
    decide(engine, "HPG")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert main() == 0  # no engine: $DATABASE_URL's
    assert "1 filled, 0 due but left empty" in summary.read_text(encoding="utf-8")


def test_a_failed_update_does_not_print_the_row(engine: Engine) -> None:
    bars(engine, "HPG", path(*[20.0] * len(S)))
    decide(engine, "HPG")
    with engine.begin() as connection:  # a CHECK no row can pass: the UPDATE of the script fails
        connection.execute(text("ALTER TABLE vn_stock_decisions ADD CONSTRAINT ck_refuse_all CHECK (false) NOT VALID"))
    try:
        with pytest.raises(RuntimeError, match="CheckViolation 23514") as error:
            main(engine)
    finally:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE vn_stock_decisions DROP CONSTRAINT ck_refuse_all"))
    assert error.value.__suppress_context__  # the traceback does not show the database error with the failing row
