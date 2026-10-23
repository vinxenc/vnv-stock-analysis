from datetime import UTC, date, datetime

import pytest

from libs.prices import VPS, Price, PriceNotFoundError, PriceSource

TARGET = "libs.prices.tradingview.http_get_json"


def ts(*args: int) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp())


# two sessions; the second one is the latest and must be picked
PAYLOAD = {
    "t": [ts(2026, 10, 22, 3), ts(2026, 10, 23, 3)],
    "o": [58.0, 57.2],
    "h": [58.7, 57.2],
    "l": [57.3, 56.6],
    "c": [57.4, 57.0],
    "v": [10088500, 7090600],
}


def test_get_latest_price(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []
    monkeypatch.setattr(TARGET, lambda url: urls.append(url) or PAYLOAD)
    source = VPS()

    price = source.get_latest_price("fpt")

    assert isinstance(source, PriceSource)
    assert price == Price(
        symbol="FPT", source="VPS", date=date(2026, 10, 23), open=57.2, high=57.2, low=56.6, close=57.0, volume=7090600
    )
    assert urls[0].startswith("https://histdatafeed.vps.com.vn/") and "symbol=FPT&" in urls[0]


def test_unknown_ticker_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TARGET, lambda url: {"t": []})

    with pytest.raises(PriceNotFoundError, match="ZZZ"):
        VPS().get_latest_price("ZZZ")
