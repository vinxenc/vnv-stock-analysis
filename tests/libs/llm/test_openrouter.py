import json

import niquests
import pytest

from libs.decision.llm import Answer
from libs.llm import Completion, LLMError, LLMProvider, OpenRouter
from libs.llm.openrouter import MAX_RETRY_WAIT, RETRY_WAIT, TIMEOUT, URL

MODEL = "anthropic/claude-opus-5.5"
GOOD = '{"decision": "buy", "probability": 0.62, "reason": "Xu hướng tăng."}'


class FakeResponse:
    """What `niquests.post(..., stream=True)` gives: a status, headers and a body read in chunks. `body` is sent as
    JSON, or as it is when it is bytes."""

    def __init__(self, status: int, body: object, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.body = body
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def iter_content(self) -> list[bytes]:
        raw = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()
        return [raw[:10], raw[10:]]


def completion(content: str | None, finish_reason: str = "stop") -> FakeResponse:
    return FakeResponse(
        200,
        {
            "model": MODEL,
            "choices": [{"finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
        },
    )


def error_body(code: int, message: str = "upstream failed") -> dict:
    return {"error": {"code": code, "message": message}}


class Calls(list):
    """Every `niquests.post` the provider made; `responses` is what they are answered with, in order, and `slept`
    the waits before a retry."""

    responses: list
    slept: list[float]


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    made = Calls()
    made.responses = []
    made.slept = []

    def post(url: str, **kwargs: object) -> FakeResponse:
        made.append({"url": url, **kwargs})
        response = made.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("libs.llm.openrouter.niquests.post", post)
    monkeypatch.setattr(OpenRouter._post.retry, "sleep", made.slept.append)  # record the wait instead of sleeping
    return made


def ask() -> Completion[Answer]:
    return OpenRouter("key").complete(MODEL, "system prompt", "user message", Answer)


def test_a_good_answer(calls: Calls) -> None:
    calls.responses.append(completion(GOOD))
    provider = OpenRouter("key")
    result = provider.complete(MODEL, "system prompt", "user message", Answer)
    assert isinstance(provider, LLMProvider)
    assert result.answer == Answer(decision="buy", probability=0.62, reason="Xu hướng tăng.")
    assert (result.model, result.input_tokens, result.output_tokens) == (MODEL, 1000, 200)
    call = calls[0]
    assert call["url"] == URL
    assert call["headers"] == {"Authorization": "Bearer key"}
    payload = call["json"]
    assert payload["model"] == MODEL
    assert "models" not in payload  # no fallback model
    assert payload["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user message"},
    ]
    assert payload["provider"] == {"require_parameters": True}
    schema = payload["response_format"]["json_schema"]
    assert (payload["response_format"]["type"], schema["name"], schema["strict"]) == ("json_schema", "Answer", True)
    assert schema["schema"]["additionalProperties"] is False
    assert "minimum" not in json.dumps(schema["schema"])  # structured output takes no numeric bounds


def test_the_key_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    assert OpenRouter().api_key == "from-env"


@pytest.mark.parametrize("value", [None, ""])  # an unset GitHub secret is an empty string
def test_a_missing_key_is_refused_before_any_call(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    if value is not None:
        monkeypatch.setenv("OPENROUTER_API_KEY", value)
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY is not set"):
        OpenRouter()


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ('{"decision": "buy", "probability": 1.3, "reason": "SECRET"}', "probability: value_error"),
        ('{"decision": "hold", "probability": 0.5, "reason": "SECRET"}', "decision: enum"),
        ('{"decision": "buy", "reason": "SECRET"', "answer: json_invalid"),
        # the name of an extra key is the answer's own text: it is not a declared field, so it is not reported
        ('{"decision": "buy", "probability": 0.5, "reason": "x", "SECRET buy 1.3": 1}', "answer: extra_forbidden"),
    ],
)
def test_an_answer_that_does_not_fit_names_the_field_never_its_value(calls: Calls, content: str, problem: str) -> None:
    calls.responses.append(completion(content))
    with pytest.raises(LLMError, match=problem) as error:
        ask()
    assert "SECRET" not in str(error.value)
    assert "1.3" not in str(error.value)
    assert error.value.__suppress_context__  # pydantic's own error, which quotes the answer, is not in the traceback


@pytest.mark.parametrize(
    ("content", "finish_reason"), [(None, "stop"), ("", "content_filter"), (GOOD, "error"), (GOOD[:20], "length")]
)
def test_no_answer(calls: Calls, content: str | None, finish_reason: str) -> None:
    calls.responses.append(completion(content, finish_reason))
    with pytest.raises(LLMError, match=f"finish_reason={finish_reason}"):
        ask()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},  # no choices
        {"choices": []},
        {"choices": [{"finish_reason": "stop"}]},  # no message
        {"choices": [{"finish_reason": "stop", "message": None}]},
        {"choices": "nothing"},
    ],
)
def test_an_unexpected_response_is_an_llm_error(calls: Calls, body: dict) -> None:
    calls.responses.append(FakeResponse(200, body))
    with pytest.raises(LLMError, match="unexpected response"):
        ask()


@pytest.mark.parametrize("usage", [None, "none", {}])
def test_a_missing_usage_does_not_discard_the_answer(calls: Calls, usage: object) -> None:
    response = completion(GOOD)
    response.body["usage"] = usage
    calls.responses.append(response)
    result = ask()
    assert (result.answer.decision, result.input_tokens, result.output_tokens) == ("buy", 0, 0)


def test_a_client_error_is_not_retried(calls: Calls) -> None:
    calls.responses.append(FakeResponse(401, error_body(401, "No auth credentials found")))
    with pytest.raises(LLMError, match="HTTP 401, error 401: No auth credentials found"):
        ask()
    assert len(calls) == 1


def test_a_client_error_in_a_200_body_is_not_retried(calls: Calls) -> None:
    calls.responses.append(FakeResponse(200, error_body(400, "bad schema")))
    with pytest.raises(LLMError, match="HTTP 200, error 400: bad schema"):
        ask()
    assert len(calls) == 1


@pytest.mark.parametrize("body", [b"<html>not json</html>", ["a", "list"], None])
def test_a_body_that_is_not_a_json_object(calls: Calls, body: object) -> None:
    calls.responses.append(FakeResponse(200, body))
    with pytest.raises(LLMError, match="HTTP 200, error None: the body is not a JSON object"):
        ask()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure",
    [
        FakeResponse(503, {}),
        FakeResponse(429, error_body(429)),
        FakeResponse(408, error_body(408)),
        FakeResponse(502, b"<html>bad gateway</html>"),
        FakeResponse(200, error_body(502)),  # an upstream failure reported inside a 200
        FakeResponse(200, error_body(429)),
        niquests.ConnectionError("down"),
    ],
)
def test_a_transient_failure_is_retried_once(calls: Calls, failure: object) -> None:
    calls.responses.extend([failure, completion(GOOD)])
    assert ask().answer.decision == "buy"
    assert len(calls) == 2
    assert calls.slept == [RETRY_WAIT]


@pytest.mark.parametrize(
    ("header", "waited"),
    [("30", 30), ("600", MAX_RETRY_WAIT), ("-1", 0), ("Wed, 21 Oct 2026 07:28:00 GMT", RETRY_WAIT)],
)
def test_the_retry_waits_what_retry_after_says(calls: Calls, header: str, waited: float) -> None:
    calls.responses.extend([FakeResponse(429, error_body(429), {"Retry-After": header}), completion(GOOD)])
    ask()
    assert calls.slept == [waited]


def test_a_transient_failure_twice_gives_up(calls: Calls) -> None:
    calls.responses.extend([FakeResponse(200, error_body(502)), niquests.Timeout("slow")])
    with pytest.raises(LLMError, match="openrouter: Timeout"):
        ask()
    assert len(calls) == 2


def test_a_body_that_keeps_trickling_in_is_cut_off_at_the_deadline(
    calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter(range(0, 100 * TIMEOUT, TIMEOUT - 1))  # every look at the clock is almost a whole TIMEOUT later
    monkeypatch.setattr("libs.llm.openrouter.time.monotonic", lambda: next(clock))
    calls.responses.extend([completion(GOOD), completion(GOOD)])  # two chunks each: the second is past the deadline
    with pytest.raises(LLMError, match=f"no complete answer within {TIMEOUT} s"):
        ask()
    assert len(calls) == 2  # retried once, like any timeout
    assert all(call["stream"] and call["timeout"] == TIMEOUT for call in calls)
