import os

import niquests
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from .base import Completion, LLMError, LLMProvider

URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 600  # seconds for one answer: a reasoning model can take minutes
MAX_TOKENS = 16000  # reasoning included; an answer cut off here fails the schema
NO_ANSWER = {"error", "content_filter", "length"}  # finish reasons whose content is not an answer


class TransientLLMError(LLMError):
    """A network error, a 429 or a 5xx: worth one more try."""


class OpenRouter(LLMProvider):
    """Chat completions of openrouter.ai with a JSON schema `response_format`. One `model`, never a `models` list: a
    fallback model would answer under the name of the one asked."""

    name = "openrouter"

    def __init__(self, api_key: str | None = None) -> None:
        # an unset GitHub secret arrives as an empty string: refuse it here, not as a 401 on the first call
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise LLMError("openrouter: $OPENROUTER_API_KEY is not set")

    def complete[T: BaseModel](self, model: str, system: str, user: str, schema: type[T]) -> Completion[T]:
        body = self._post(
            {
                "model": model,
                "max_tokens": MAX_TOKENS,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "strict": True, "schema": schema.model_json_schema()},
                },
                # only an upstream that honours response_format, instead of one that silently ignores it
                "provider": {"require_parameters": True},
            }
        )
        choice = body["choices"][0]
        content = choice["message"].get("content")
        if not content or choice.get("finish_reason") in NO_ANSWER:
            raise LLMError(f"no answer from {model}: finish_reason={choice.get('finish_reason')}")
        try:
            answer = schema.model_validate_json(content)
        except ValidationError as error:
            # the fields and what is wrong with them, never their values (pydantic's own message quotes the input)
            problems = ", ".join(
                f"{'.'.join(map(str, problem['loc'])) or 'json'}: {problem['type']}"
                for problem in error.errors(include_input=False, include_url=False)
            )
            raise LLMError(f"the answer of {model} does not fit {schema.__name__} ({problems})") from None
        usage = body["usage"]
        return Completion(answer, body.get("model", model), usage["prompt_tokens"], usage["completion_tokens"])

    @retry(
        retry=retry_if_exception_type(TransientLLMError), stop=stop_after_attempt(2), wait=wait_fixed(5), reraise=True
    )
    def _post(self, payload: dict) -> dict:
        """The JSON body of a successful call. An error can also come with HTTP 200, as an `error` object."""
        try:
            response = niquests.post(
                URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload, timeout=TIMEOUT
            )
        except niquests.RequestException as error:
            raise TransientLLMError(f"openrouter: {type(error).__name__}") from None
        status = response.status_code
        if status == 429 or status >= 500:
            raise TransientLLMError(f"openrouter: HTTP {status}")
        try:
            body = response.json()
        except ValueError:
            raise LLMError(f"openrouter: HTTP {status}, not JSON") from None
        if status >= 400 or "error" in body:
            error = body.get("error") or {}
            raise LLMError(f"openrouter: HTTP {status}, error {error.get('code')}: {str(error.get('message'))[:200]}")
        return body
