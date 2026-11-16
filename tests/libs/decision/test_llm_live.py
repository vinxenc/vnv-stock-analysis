"""One paid call to the real API, with $OPENROUTER_API_KEY set:
`uv run pytest -m live --no-cov -s tests/libs/decision`."""

from pathlib import Path

import pytest

from libs.decision.candidates import build_input
from libs.decision.llm import LlmDecider
from libs.llm import OpenRouter
from tests.libs.decision.fakes import DAY, report, result, write_history

pytestmark = pytest.mark.live


def test_live_one_symbol(tmp_path: Path) -> None:
    write_history(tmp_path, "HPG")
    candidates = build_input(report(result("HPG", 71.5)), tmp_path).symbols
    decision = LlmDecider(OpenRouter()).decide_all(DAY, candidates)["HPG"]
    assert 0 <= decision.probability <= 1
    assert decision.reason
    print(decision.decision, decision.probability, decision.reason, decision.input["answered_by"])
