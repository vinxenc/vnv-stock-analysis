from datetime import date
from typing import Any

import niquests
import pytest
from pydantic import ValidationError

from libs.prices import Price, PriceNotFoundError, PriceSource
from libs.prices.base import UA, http_get_json, validate_symbol


def make(**overrides: float | str) -> Price:
    fields: dict[str, Any] = dict(
        symbol="FPT", source="X", date="2026-10-23", open=57.2, high=57.5, low=56.6, close=57.0, volume=100
    )
    return Price(**{**fields, **overrides})


def fake_response(status: int, body: bytes = b"{}") -> niquests.Response:
    result = niquests.Response()
    result.status_code = status
    result._content = body
    result.url = "https://example.test/x"
    return result


def test_http_get_json_returns_body_with_user_agent_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_get(url: str, headers: dict[str, str], timeout: int) -> niquests.Response:
        seen.append((url, headers, timeout))
        return fake_response(200, b'{"ok": true}')

    monkeypatch.setattr(niquests, "get", fake_get)

    assert http_get_json("https://example.test/x") == {"ok": True}
    assert seen == [("https://example.test/x", UA, 15)]


def test_http_get_json_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(niquests, "get", lambda url, headers, timeout: fake_response(503))

    with pytest.raises(niquests.HTTPError) as error:
        http_get_json("https://example.test/x")
    assert error.value.response.status_code == 503


@pytest.mark.parametrize("raw, expected", [("fpt", "FPT"), (" vnm ", "VNM"), ("E1VFVN30", "E1VFVN30")])
def test_validate_symbol_normalises(raw: str, expected: str) -> None:
    assert validate_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", "FPT&resolution=1W", "FPT~floor:HOSE", "F PT", "../x", "TOOLONGSYMBOL1"])
def test_validate_symbol_rejects(raw: str) -> None:
    with pytest.raises(PriceNotFoundError, match="invalid symbol"):
        validate_symbol(raw)


def test_price_coerces_and_validates() -> None:
    price = make(volume="5")

    assert price.date == date(2026, 10, 23) and price.volume == 5
    with pytest.raises(ValidationError):
        Price(symbol="FPT", source="X")


@pytest.mark.parametrize(
    "bad",
    [
        {"low": 0},  # non-positive price
        {"close": -1},
        {"volume": -1},
        {"high": float("inf")},  # non-finite
        {"close": float("nan")},
    ],
)
def test_price_rejects_inconsistent_values(bad: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        make(**bad)


def test_price_allows_zero_volume() -> None:
    assert make(volume=0).volume == 0


def test_price_source_is_abstract() -> None:
    with pytest.raises(TypeError):
        PriceSource()
