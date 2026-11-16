import json

import niquests
import pytest

from libs.decision.llm import Answer
from libs.llm import LLMError, LLMProvider, OpenRouter
from libs.llm.openrouter import URL

MODEL = "anthropic/claude-opus-5.5"
GOOD = '{"decision": "buy", "probability": 0.62, "reason": "Xu hướng tăng."}'


class FakeResponse:
    def __init__(self, status: int, body: object) -> None:
        self.status_code = status
        self.body = body

    def json(self) -> object:
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def completion(content: str | None, finish_reason: str = "stop") -> FakeResponse:
    return FakeResponse(
        200,
        {
            "model": MODEL,
            "choices": [{"finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
        },
    )


class Calls(list):
    """Every `niquests.post` the provider made; `responses` is what they are answered with, in order."""

    responses: list


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    made = Calls()
    made.responses = []

    def post(url: str, **kwargs: object) -> FakeResponse:
        made.append({"url": url, **kwargs})
        response = made.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("libs.llm.openrouter.niquests.post", post)
    monkeypatch.setattr(OpenRouter._post.retry, "sleep", lambda seconds: None)  # no wait between the two tries
    return made


def ask() -> object:
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
        ('{"decision": "buy", "reason": "SECRET"', "json: json_invalid"),
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


def test_an_error_body_with_http_200(calls: Calls) -> None:
    calls.responses.append(FakeResponse(200, {"error": {"code": 502, "message": "upstream failed"}}))
    with pytest.raises(LLMError, match="HTTP 200, error 502: upstream failed"):
        ask()
    assert len(calls) == 1


def test_a_client_error_is_not_retried(calls: Calls) -> None:
    calls.responses.append(FakeResponse(401, {"error": {"code": 401, "message": "No auth credentials found"}}))
    with pytest.raises(LLMError, match="HTTP 401, error 401: No auth credentials found"):
        ask()
    assert len(calls) == 1


def test_a_body_that_is_not_json(calls: Calls) -> None:
    calls.responses.append(FakeResponse(200, ValueError("not json")))
    with pytest.raises(LLMError, match="HTTP 200, not JSON"):
        ask()


@pytest.mark.parametrize("failure", [FakeResponse(503, {}), FakeResponse(429, {}), niquests.ConnectionError("down")])
def test_a_transient_failure_is_retried_once(calls: Calls, failure: object) -> None:
    calls.responses.extend([failure, completion(GOOD)])
    assert ask().answer.decision == "buy"
    assert len(calls) == 2


def test_a_transient_failure_twice_gives_up(calls: Calls) -> None:
    calls.responses.extend([FakeResponse(503, {}), niquests.Timeout("slow")])
    with pytest.raises(LLMError, match="openrouter: Timeout"):
        ask()
    assert len(calls) == 2
