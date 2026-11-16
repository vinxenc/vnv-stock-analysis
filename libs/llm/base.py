"""The LLM provider the deciders depend on, as an interface (like `PriceSource` for the price sources).

A decider asks an `LLMProvider` for one answer shaped by a pydantic model; which service answers (OpenRouter today) is
decided once, where the provider is created (`scripts/vn_stock_llm_decision.py`). To add a provider, subclass
`LLMProvider` in this package and export it in `__init__.py`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from pydantic import BaseModel


class LLMError(RuntimeError):
    """The provider gave no usable answer: an HTTP or API error, a refusal, an answer that does not fit the schema.
    Its message never quotes the answer: the job logs are public."""


@dataclass(frozen=True)
class Completion[T: BaseModel]:
    answer: T
    model: str  # the model that answered, as the provider reports it
    input_tokens: int
    output_tokens: int


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete[T: BaseModel](self, model: str, system: str, user: str, schema: type[T]) -> Completion[T]:
        """One answer of `model` to the `user` message under the `system` prompt, validated against `schema` (sent as
        its JSON schema, so keep to what a JSON schema for structured output allows: no numeric bounds).

        Raises LLMError when there is no usable answer.
        """
