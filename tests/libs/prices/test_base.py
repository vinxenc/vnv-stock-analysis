import io
import urllib.request
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from libs.prices import PriceNotFoundError, Prices, PriceSource
from libs.prices.base import UA, http_get_json, validate_symbol


def make(**overrides: float | str) -> Prices:
    fields: dict[str, Any] = dict(
        symbol="FPT", source="X", date="2026-10-23", open=57.2, high=57.5, low=56.6, close=57.0, volume=100
    )
    return Prices(**{**fields, **overrides})


def test_http_get_json_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_urlopen(req: urllib.request.Request, timeout: int) -> io.BytesIO:
        seen.append((req.full_url, req.get_header("User-agent"), timeout))
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert http_get_json("https://example.test/x") == {"ok": True}
    assert seen == [("https://example.test/x", UA["User-Agent"], 15)]


@pytest.mark.parametrize("raw, expected", [("fpt", "FPT"), (" vnm ", "VNM"), ("E1VFVN30", "E1VFVN30")])
def test_validate_symbol_normalises(raw: str, expected: str) -> None:
    assert validate_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", "FPT&resolution=1W", "FPT~floor:HOSE", "F PT", "../x", "TOOLONGSYMBOL1"])
def test_validate_symbol_rejects(raw: str) -> None:
    with pytest.raises(PriceNotFoundError, match="invalid symbol"):
        validate_symbol(raw)


def test_prices_coerces_and_validates() -> None:
    p = make(volume="5")

    assert p.date == date(2026, 10, 23) and p.volume == 5
    with pytest.raises(ValidationError):
        Prices(symbol="FPT", source="X")


@pytest.mark.parametrize(
    "bad",
    [
        {"low": 0},  # non-positive price
        {"close": -1},
        {"volume": -1},
        {"low": 58.0},  # low above open/close
        {"high": 56.0},  # high below open/close
    ],
)
def test_prices_rejects_inconsistent_values(bad: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        make(**bad)


def test_prices_tolerates_rounding_noise() -> None:
    assert make(open=57.505).high == 57.5  # 0.005 above high, within tolerance


def test_prices_allows_zero_volume() -> None:
    assert make(volume=0).volume == 0


def test_price_not_found_is_a_value_error() -> None:
    assert issubclass(PriceNotFoundError, ValueError)


def test_price_source_is_abstract() -> None:
    with pytest.raises(TypeError):
        PriceSource()
