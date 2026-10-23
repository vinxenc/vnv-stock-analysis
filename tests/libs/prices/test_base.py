import io
import urllib.request
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from libs.prices import Prices, PriceSource
from libs.prices.base import UA, http_get_json, tradingview_last


def ts(*args: int) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp())


def test_http_get_json_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_urlopen(req: urllib.request.Request, timeout: int) -> io.BytesIO:
        seen.append((req.full_url, req.get_header("User-agent"), timeout))
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert http_get_json("https://example.test/x") == {"ok": True}
    assert seen == [("https://example.test/x", UA["User-Agent"], 15)]


def test_tradingview_last_picks_latest_row() -> None:
    d = {
        "t": [ts(2026, 10, 22, 3), ts(2026, 10, 23, 3)],
        "o": [1, 2],
        "h": [1, 3],
        "l": [1, 0.5],
        "c": [1, 2.5],
        "v": [10, 20],
    }

    p = tradingview_last("X", "FPT", d)

    assert (p.date, p.open, p.high, p.low, p.close, p.volume) == (date(2026, 10, 23), 2, 3, 0.5, 2.5, 20)


def test_tradingview_date_uses_vietnam_timezone() -> None:
    # 18:00 UTC on the 22nd is already the 23rd in UTC+7
    d = {"t": [ts(2026, 10, 22, 18)], "o": [1], "h": [1], "l": [1], "c": [1], "v": [1]}

    assert tradingview_last("X", "FPT", d).date == date(2026, 10, 23)


def test_tradingview_last_empty_raises() -> None:
    with pytest.raises(ValueError, match="FPT"):
        tradingview_last("X", "FPT", {"t": []})


def test_prices_coerces_and_validates() -> None:
    p = Prices(symbol="FPT", source="X", date="2026-10-23", open=1, high=1, low=1, close=1, volume="5")

    assert p.date == date(2026, 10, 23) and p.volume == 5
    with pytest.raises(ValidationError):
        Prices(symbol="FPT", source="X")


def test_price_source_is_abstract() -> None:
    with pytest.raises(TypeError):
        PriceSource()
