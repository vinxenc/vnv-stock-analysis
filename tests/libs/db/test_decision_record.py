import datetime as dt

import pytest
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import IntegrityError

from libs.db.models import DecisionRecord
from libs.decision.models import Decider, Verdict


def _row(**changes: object) -> dict[str, object]:
    row = {
        "date": dt.date(2026, 11, 13),
        "symbol": "AAA",
        "model_name": "anthropic/claude-opus-5-5",
        "decider": Decider.LLM,
        "decision": Verdict.BUY,
        "probability": 0.6,
        "input": {"symbol": "AAA"},
    }
    return row | changes


def test_layout() -> None:
    table = DecisionRecord.__table__
    assert table.name == "vn_stock_decisions"
    assert [column.name for column in table.primary_key.columns] == ["date", "symbol", "model_name"]


def test_every_decider_and_verdict_is_accepted_and_the_outcome_starts_empty(engine: Engine) -> None:
    """`alembic check` ignores CHECK constraints: the database must accept exactly the members of the two enums."""
    rows = [
        _row(model_name=f"{decider}/{verdict}", decider=decider, decision=verdict)
        for decider in Decider
        for verdict in Verdict
    ]
    with engine.begin() as connection:
        connection.execute(insert(DecisionRecord), rows)
        stored = connection.execute(select(DecisionRecord.__table__)).mappings().all()
    assert len(stored) == len(rows)
    assert all(row["return_5"] is None and row["hit"] is None and row["reason"] is None for row in stored)
    assert all(row["created_at"].tzinfo is not None for row in stored)  # filled by Postgres, timezone-aware


@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ({"decider": "claude"}, "ck_vn_stock_decisions_decider"),  # a model, not a kind
        ({"decision": "BUY"}, "ck_vn_stock_decisions_decision"),
        ({"probability": 1.3}, "ck_vn_stock_decisions_probability"),
        ({"probability": -0.1}, "ck_vn_stock_decisions_probability"),
        ({"probability": float("nan")}, "ck_vn_stock_decisions_probability"),
    ],
)
def test_a_bad_value_is_refused(engine: Engine, change: dict[str, object], constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint), engine.begin() as connection:
        connection.execute(insert(DecisionRecord), [_row(**change)])


def test_two_models_of_one_kind_can_answer_the_same_symbol(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(insert(DecisionRecord), [_row(), _row(model_name="openai/gpt-x")])
        assert connection.execute(text("SELECT count(*) FROM vn_stock_decisions")).scalar() == 2


def test_a_duplicate_key_is_refused(engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="vn_stock_decisions_pkey"), engine.begin() as connection:
        connection.execute(insert(DecisionRecord), [_row(), _row(probability=0.7)])


def test_the_probability_bounds_are_accepted(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(insert(DecisionRecord), [_row(probability=0), _row(symbol="BBB", probability=1)])
        assert connection.execute(text("SELECT count(*) FROM vn_stock_decisions")).scalar() == 2
