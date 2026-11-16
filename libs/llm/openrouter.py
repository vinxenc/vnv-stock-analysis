import json
import os
import time

import niquests
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exception

from .base import Completion, LLMError, LLMProvider

URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 300  # seconds for one answer, from the request to its last byte: a reasoning model can take minutes
MAX_TOKENS = 16000  # reasoning included; an answer cut off here fails the schema
NO_ANSWER = {"error", "content_filter", "length"}  # finish reasons whose content is not an answer
RETRY_WAIT = 5  # seconds before the one retry, unless the response has a Retry-After
MAX_RETRY_WAIT = 60  # a longer Retry-After is not worth the job's time


class TransientLLMError(LLMError):
    """A network error, or an error whose status or code is 408, 429 or 5xx: worth one more try."""

    def __init__(self, message: str, retry_after: float = RETRY_WAIT) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def is_transient(code: object) -> bool:
    return isinstance(code, int) and (code in (408, 429) or code >= 500)


def retry_wait(header: str | None) -> float:
    """Seconds to wait from a `Retry-After` header (the seconds form only), between 0 and MAX_RETRY_WAIT."""
    try:
        return min(max(float(header), 0), MAX_RETRY_WAIT)
    except (TypeError, ValueError):  # no header, or the HTTP-date form
        return RETRY_WAIT


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
        try:
            choice = body["choices"][0]
            content = choice["message"].get("content")
            finish_reason = choice.get("finish_reason")
        except (LookupError, TypeError, AttributeError) as error:
            raise LLMError(f"openrouter: unexpected response of {model} ({type(error).__name__})") from None
        if not content or finish_reason in NO_ANSWER:
            raise LLMError(f"no answer from {model}: finish_reason={finish_reason}")
        try:
            answer = schema.model_validate_json(content)
        except ValidationError as error:
            # the declared field and what is wrong with it, never a value (pydantic's own message quotes the input)
            # and never another location: the name of an extra key is the answer's own text
            fields = schema.model_fields
            problems = ", ".join(
                f"{loc[0] if (loc := problem['loc']) and loc[0] in fields else 'answer'}: {problem['type']}"
                for problem in error.errors(include_input=False, include_url=False)
            )
            raise LLMError(f"the answer of {model} does not fit {schema.__name__} ({problems})") from None
        usage = body.get("usage")
        usage = usage if isinstance(usage, dict) else {}  # token counts are for the log: never worth a paid answer
        return Completion(
            answer, body.get("model", model), usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        )

    @retry(
        retry=retry_if_exception_type(TransientLLMError),
        stop=stop_after_attempt(2),
        wait=wait_exception(lambda error: error.retry_after),
        reraise=True,
    )
    def _post(self, payload: dict) -> dict:
        """The JSON object of a successful call. An error is an HTTP status or an `error` object in the body, which
        OpenRouter also sends with HTTP 200 (an upstream failure): both are read the same way."""
        deadline = time.monotonic() + TIMEOUT
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            with niquests.post(URL, headers=headers, json=payload, timeout=TIMEOUT, stream=True) as response:
                # `timeout` only bounds the wait for the next bytes, so a body that keeps trickling in would never
                # end: it is read in chunks and cut off at the deadline
                chunks = []
                for chunk in response.iter_content():
                    if time.monotonic() > deadline:
                        raise TransientLLMError(f"openrouter: no complete answer within {TIMEOUT} s")
                    chunks.append(chunk)
        except niquests.RequestException as error:
            raise TransientLLMError(f"openrouter: {type(error).__name__}") from None
        status = response.status_code
        try:
            body = json.loads(b"".join(chunks))
        except ValueError:
            body = None
        error = body.get("error") if isinstance(body, dict) else "the body is not a JSON object"
        if status < 400 and not error:
            return body
        code, detail = (error.get("code"), error.get("message")) if isinstance(error, dict) else (None, error)
        message = f"openrouter: HTTP {status}, error {code}: {str(detail)[:200]}"
        if is_transient(status) or is_transient(code):
            raise TransientLLMError(message, retry_wait(response.headers.get("Retry-After")))
        raise LLMError(message)
