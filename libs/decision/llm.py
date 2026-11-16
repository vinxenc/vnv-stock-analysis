"""The LLM decider (Phase 2): one model, reached through any `LLMProvider`, answers buy or skip for each candidate
with the probability of buy and a short reason. One call per symbol, the answer validated against `Answer`."""

import datetime as dt
import json
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait

from pydantic import field_validator

from libs.analysis.models import Model
from libs.decision.base import BaseDecider, Decision
from libs.decision.candidates import Candidate
from libs.decision.models import Decider, Verdict
from libs.llm import Completion, LLMProvider
from libs.logger import Logger, LogxideLogger

PROMPT_VERSION = 1  # stored with every answer: bump it whenever SYSTEM or the user message changes
WORKERS = 8  # calls in flight at once: a day with many candidates must stay far from the job's timeout

SYSTEM = """\
You judge one stock listed in Vietnam (HOSE) for a short-term screen. The user message is one JSON object: the session \
date (`session`) and one `candidate` with its screening score (0 to 100), its theme scores, its technical indicators \
with their raw values, its flags and its last daily bars up to the session (adjusted prices, thousand VND).

Question: will the close 5 market sessions after `session` be at least 3% above the close of `session`?

Answer with:
- probability: your probability, from 0 to 1, that the answer is yes. Most stocks do not gain 3% in 5 sessions: give \
the number you believe, not a confident one.
- decision: "buy" if you judge the symbol worth buying for that target, otherwise "skip".
- reason: two or three sentences in Vietnamese naming the data points that decided it.

Judge only from the data given. Do not use or invent news, financials, events or other symbols. An indicator whose \
status is `unavailable` has no value: say so if it matters, never guess it."""

logger = LogxideLogger("llm_decider")


class Answer(Model):
    decision: Verdict
    probability: float
    reason: str

    @field_validator("probability")
    @classmethod
    def _between_0_and_1(cls, value: float) -> float:
        """A validator, not `Field(ge=0, le=1)`: the JSON schema sent for structured output takes no numeric bounds."""
        if not 0 <= value <= 1:
            raise ValueError("not between 0 and 1")
        return value


class LlmDecider(BaseDecider):
    kind = Decider.LLM

    def __init__(self, provider: LLMProvider, model: str, log: Logger = logger) -> None:
        """`model` is the id as the provider names it (`anthropic/claude-opus-5.5` on OpenRouter). It is also the
        `model_name` of the rows, without a provider prefix: the provider is in `input`."""
        self.provider = provider
        self.model_name = model
        self.log = log

    def decide_all(self, session: dt.date, candidates: list[Candidate]) -> dict[str, Decision]:
        """All or nothing: the first failure is raised once the calls in flight have ended; the calls not started
        yet are cancelled, so they are not paid for. The token totals of the calls that answered are logged either
        way."""
        pool = ThreadPoolExecutor(max_workers=WORKERS)
        futures = [pool.submit(self._ask, session, candidate) for candidate in candidates]
        wait(futures, return_when=FIRST_EXCEPTION)
        pool.shutdown(cancel_futures=True)  # waits for the calls in flight
        answered = [future.result() for future in futures if not future.cancelled() and not future.exception()]
        self.log.info(
            "%s through %s: %d of %d calls answered, %d input tokens, %d output tokens",
            self.model_name,
            self.provider.name,
            len(answered),
            len(candidates),
            sum(completion.input_tokens for _, completion in answered),
            sum(completion.output_tokens for _, completion in answered),
        )
        for future in futures:
            if not future.cancelled():
                future.result()  # raises the first failure, in the candidates' order
        return {
            candidate.symbol: Decision(
                **completion.answer.model_dump(),
                input={
                    "prompt_version": PROMPT_VERSION,
                    "provider": self.provider.name,
                    "answered_by": completion.model,
                    **question,
                },
            )
            for candidate, (question, completion) in zip(candidates, answered, strict=True)
        }

    def _ask(self, session: dt.date, candidate: Candidate) -> tuple[dict, Completion[Answer]]:
        """The question sent about one candidate and its answer."""
        question = {"session": session.isoformat(), "candidate": candidate.model_dump(mode="json")}
        return question, self.provider.complete(self.model_name, SYSTEM, json.dumps(question), Answer)
