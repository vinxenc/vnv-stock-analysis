"""The LLM decider (Phase 2): one model, reached through any `LLMProvider`, answers buy or skip for each candidate
with the probability of buy and a short reason. One call per symbol, the answer validated against `Answer`."""

import datetime as dt
import json

from pydantic import field_validator

from libs.analysis.models import Model
from libs.decision.base import BaseDecider, Decision
from libs.decision.candidates import Candidate
from libs.decision.models import Decider, Verdict
from libs.llm import LLMProvider
from libs.logger import Logger, LogxideLogger

MODEL = "anthropic/claude-opus-5.5"  # the id as the provider (OpenRouter) names it
PROMPT_VERSION = 1  # stored with every answer: bump it whenever SYSTEM or the user message changes

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

    def __init__(self, provider: LLMProvider, model: str = MODEL, log: Logger = logger) -> None:
        self.provider = provider
        self.model = model
        self.model_name = model  # the provider's id of the model, no provider prefix (the provider is in `input`)
        self.log = log

    def decide_all(self, session: dt.date, candidates: list[Candidate]) -> dict[str, Decision]:
        decisions = {}
        tokens_in = tokens_out = 0
        # ponytail: one call at a time (at most the ~90 liquid symbols); a thread pool if it gets slow
        for candidate in candidates:
            question = {"session": session.isoformat(), "candidate": candidate.model_dump(mode="json")}
            completion = self.provider.complete(self.model, SYSTEM, json.dumps(question), Answer)
            tokens_in += completion.input_tokens
            tokens_out += completion.output_tokens
            decisions[candidate.symbol] = Decision(
                **completion.answer.model_dump(),
                input={
                    "prompt_version": PROMPT_VERSION,
                    "provider": self.provider.name,
                    "answered_by": completion.model,
                    **question,
                },
            )
        self.log.info(
            "%s through %s: %d calls, %d input tokens, %d output tokens",
            self.model,
            self.provider.name,
            len(decisions),
            tokens_in,
            tokens_out,
        )
        return decisions
