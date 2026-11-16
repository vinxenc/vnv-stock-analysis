import json
import threading
import time
from pathlib import Path

import pytest
from pydantic import BaseModel

from libs.decision.base import BaseDecider, Decision
from libs.decision.candidates import Candidate, build_input
from libs.decision.llm import PROMPT_VERSION, SYSTEM, WORKERS, Answer, LlmDecider
from libs.decision.models import Decider, Verdict
from libs.llm import Completion, LLMError, LLMProvider
from tests.libs.decision.fakes import DAY, report, result, write_history

MODEL = "anthropic/claude-opus-5.5"


class FakeProvider(LLMProvider):
    """Answers the call about a symbol with `answers[symbol]` (the calls run in threads, in no fixed order); an
    exception there is raised at once. With `barrier`, the first WORKERS calls only go on once they are all in flight
    together; with `delay`, an answer takes that many seconds."""

    name = "fake"

    def __init__(
        self, barrier: threading.Barrier | None = None, delay: float = 0, **answers: Answer | Exception
    ) -> None:
        self.answers = answers
        self.barrier = barrier
        self.delay = delay
        self.calls: dict[str, tuple[str, str, str, type[BaseModel]]] = {}

    def complete[T: BaseModel](self, model: str, system: str, user: str, schema: type[T]) -> Completion[T]:
        symbol = json.loads(user)["candidate"]["symbol"]
        self.calls[symbol] = (model, system, user, schema)
        answer = self.answers[symbol]
        if isinstance(answer, Exception):
            raise answer
        if self.barrier and len(self.calls) <= WORKERS:
            self.barrier.wait(5)  # BrokenBarrierError when the calls come one after another
        time.sleep(self.delay)
        return Completion(answer, f"{model}-20261101", 1000, 200)


class Messages(list):
    """A Logger that keeps what it is told."""

    def info(self, msg: str, *args: object) -> None:
        self.append(msg % args)

    debug = warning = error = info


def candidates(tmp_path: Path, *codes: str) -> list[Candidate]:
    for code in codes:
        write_history(tmp_path, code)
    return build_input(report(*(result(code, 71.5) for code in codes)), tmp_path).symbols


def buy() -> Answer:
    return Answer(decision=Verdict.BUY, probability=0.62, reason="Tăng.")


def test_one_decision_per_candidate_with_what_it_was_judged_from(tmp_path: Path) -> None:
    provider = FakeProvider(HPG=buy(), FPT=Answer(decision=Verdict.SKIP, probability=0.2, reason="Yếu."))
    log = Messages()
    decider = LlmDecider(provider, MODEL, log)
    decisions = decider.decide_all(DAY, candidates(tmp_path, "HPG", "FPT"))
    assert isinstance(decider, BaseDecider)
    assert (decider.kind, decider.model_name) == (Decider.LLM, MODEL)  # the model, not the provider
    assert list(decisions) == ["HPG", "FPT"]  # the candidates' order, whatever order the calls ended in
    hpg = decisions["HPG"]
    assert isinstance(hpg, Decision)
    assert (hpg.decision, hpg.probability, hpg.reason) == (Verdict.BUY, 0.62, "Tăng.")
    assert (decisions["FPT"].decision, decisions["FPT"].input["candidate"]["symbol"]) == (Verdict.SKIP, "FPT")
    assert {key: hpg.input[key] for key in ("prompt_version", "provider", "answered_by", "session")} == {
        "prompt_version": PROMPT_VERSION,
        "provider": "fake",
        "answered_by": f"{MODEL}-20261101",
        "session": DAY.isoformat(),
    }
    assert len(hpg.input["candidate"]["bars"]) == 60
    model, system, user, schema = provider.calls["HPG"]
    assert (model, system, schema) == (MODEL, SYSTEM, Answer)
    assert json.loads(user) == {"session": DAY.isoformat(), "candidate": hpg.input["candidate"]}
    assert log == [f"{MODEL} through fake: 2 of 2 calls answered, 2000 input tokens, 400 output tokens"]


def test_a_failure_stops_the_run_and_still_logs_the_tokens_spent(tmp_path: Path) -> None:
    provider = FakeProvider(HPG=buy(), FPT=LLMError("no answer"))
    log = Messages()
    with pytest.raises(LLMError, match="no answer"):
        LlmDecider(provider, MODEL, log).decide_all(DAY, candidates(tmp_path, "HPG", "FPT"))
    assert log == [f"{MODEL} through fake: 1 of 2 calls answered, 1000 input tokens, 200 output tokens"]


def test_the_calls_run_in_parallel(tmp_path: Path) -> None:
    codes = [f"S{number:02d}" for number in range(WORKERS + 4)]
    provider = FakeProvider(threading.Barrier(WORKERS), **{code: buy() for code in codes})
    decisions = LlmDecider(provider, MODEL, Messages()).decide_all(DAY, candidates(tmp_path, *codes))
    assert list(decisions) == codes


def test_a_failure_cancels_the_calls_not_started(tmp_path: Path) -> None:
    codes = [f"S{number:02d}" for number in range(WORKERS + 8)]
    answers = {code: buy() for code in codes} | {codes[0]: LLMError("no answer")}
    provider = FakeProvider(delay=0.3, **answers)  # the first call fails at once, the others are still in flight
    with pytest.raises(LLMError, match="no answer"):
        LlmDecider(provider, MODEL, Messages()).decide_all(DAY, candidates(tmp_path, *codes))
    assert len(provider.calls) < len(codes)  # the queue behind the workers was cancelled, not paid for


def test_the_model_is_the_model_name(tmp_path: Path) -> None:
    assert LlmDecider(FakeProvider(), "openai/gpt-x").model_name == "openai/gpt-x"
