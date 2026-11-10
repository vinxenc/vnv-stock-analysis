import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from libs.analysis.models import (
    AnalysisReport,
    Flag,
    IndicatorResult,
    IndicatorStatus,
    SymbolResult,
    Theme,
)

EXAMPLE = Path(__file__).parents[2] / "data" / "analysis_example.json"


def example() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_example_round_trips_unchanged() -> None:
    """The example file is the contract: a model change that alters its shape shows up here and in the diff."""
    report = AnalysisReport.model_validate(example())
    assert json.loads(report.model_dump_json()) == example()
    assert report.symbols[0].flags == [Flag.CEILING_LOCKED]
    assert report.symbols[0].indicators[1].status == IndicatorStatus.GATE_CLOSED
    assert report.symbols[1].score is None


def test_unknown_field_is_rejected() -> None:
    data = example()
    data["extra"] = 1
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(data)


def test_score_must_be_given_even_when_null() -> None:
    data = example()
    del data["symbols"][1]["score"]
    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(data)


def test_score_range() -> None:
    with pytest.raises(ValidationError):
        SymbolResult(symbol="X", score=101, coverage=90, turnover=1, themes={}, indicators=[])


def test_indicator_id_range() -> None:
    with pytest.raises(ValidationError):
        IndicatorResult(id=25, theme=Theme.TREND, status=IndicatorStatus.SCORED, points=0, max_points=3)
