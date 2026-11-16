import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from libs.decision.base import BaseDecider, Decision
from libs.decision.candidates import Candidate, build_input
from libs.decision.llm import MODEL, PROMPT_VERSION, SYSTEM, Answer, LlmDecider
from libs.decision.models import Decider, Verdict
from libs.llm import Completion, LLMError, LLMProvider
from tests.libs.decision.fakes import DAY, report, result, write_history


class FakeProvider(LLMProvider):
    """Answers each call with the next of `answers`; an exception among them is raised."""

    name = "fake"

    def __init__(self, *answers: Answer | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str, str, type[BaseModel]]] = []

    def complete[T: BaseModel](self, model: str, system: str, user: str, schema: type[T]) -> Completion[T]:
        self.calls.append((model, system, user, schema))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Completion(answer, f"{model}-20261101", 1000, 200)


def candidates(tmp_path: Path, *codes: str) -> list[Candidate]:
    for code in codes:
        write_history(tmp_path, code)
    return build_input(report(*(result(code, 71.5) for code in codes)), tmp_path).symbols


def test_one_decision_per_candidate_with_what_it_was_judged_from(tmp_path: Path) -> None:
    provider = FakeProvider(
        Answer(decision=Verdict.BUY, probability=0.62, reason="Tăng."),
        Answer(decision=Verdict.SKIP, probability=0.2, reason="Yếu."),
    )
    decider = LlmDecider(provider)
    decisions = decider.decide_all(DAY, candidates(tmp_path, "HPG", "FPT"))
    assert isinstance(decider, BaseDecider)
    assert (decider.kind, decider.model_name) == (Decider.LLM, MODEL)  # the model, not the provider
    assert list(decisions) == ["HPG", "FPT"]  # the candidates' order
    hpg = decisions["HPG"]
    assert isinstance(hpg, Decision)
    assert (hpg.decision, hpg.probability, hpg.reason) == (Verdict.BUY, 0.62, "Tăng.")
    assert {key: hpg.input[key] for key in ("prompt_version", "provider", "answered_by", "session")} == {
        "prompt_version": PROMPT_VERSION,
        "provider": "fake",
        "answered_by": f"{MODEL}-20261101",
        "session": DAY.isoformat(),
    }
    assert len(hpg.input["candidate"]["bars"]) == 60
    model, system, user, schema = provider.calls[0]
    assert (model, system, schema) == (MODEL, SYSTEM, Answer)
    assert json.loads(user) == {"session": DAY.isoformat(), "candidate": hpg.input["candidate"]}


def test_a_failing_provider_stops_the_run(tmp_path: Path) -> None:
    provider = FakeProvider(Answer(decision=Verdict.BUY, probability=0.62, reason="Tăng."), LLMError("no answer"))
    with pytest.raises(LLMError, match="no answer"):
        LlmDecider(provider).decide_all(DAY, candidates(tmp_path, "HPG", "FPT"))


def test_another_model_is_another_model_name(tmp_path: Path) -> None:
    assert LlmDecider(FakeProvider(), "openai/gpt-x").model_name == "openai/gpt-x"
