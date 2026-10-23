from datetime import UTC, date, datetime
from email.message import Message
from urllib.error import HTTPError

import pytest

from libs.prices import PriceNotFoundError
from libs.prices.tradingview import TradingViewSource, tradingview_last

TARGET = "libs.prices.tradingview.http_get_json"


def ts(*args: int) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp())


class Fake(TradingViewSource):
    name = "FAKE"

    def url(self, symbol: str, start: int, end: int) -> str:
        return f"https://example.test/{symbol}?from={start}&to={end}"


def http_error(code: int) -> HTTPError:
    return HTTPError("https://example.test", code, "err", Message(), None)


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
    with pytest.raises(PriceNotFoundError, match="FPT"):
        tradingview_last("X", "FPT", {"t": []})


def test_get_price_builds_url_with_ten_day_window(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []
    monkeypatch.setattr(TARGET, lambda url: urls.append(url) or {"t": []})

    with pytest.raises(PriceNotFoundError):
        Fake().get_price("fpt")

    path, query = urls[0].split("?")
    start, end = (int(p.split("=")[1]) for p in query.split("&"))
    assert path.endswith("/FPT") and end - start == 86400 * 10


@pytest.mark.parametrize("bad", ["FPT&x=1", ""])
def test_get_price_rejects_invalid_symbol_before_any_request(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    def boom(url: str) -> dict:
        raise AssertionError("request must not be made")

    monkeypatch.setattr(TARGET, boom)

    with pytest.raises(PriceNotFoundError, match="invalid symbol"):
        Fake().get_price(bad)


@pytest.mark.parametrize("code", [400, 404])
def test_unknown_ticker_http_errors_become_not_found(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    def fail(url: str) -> dict:
        raise http_error(code)

    monkeypatch.setattr(TARGET, fail)

    with pytest.raises(PriceNotFoundError, match=str(code)):
        Fake().get_price("ZZZ")


def test_other_http_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(url: str) -> dict:
        raise http_error(503)

    monkeypatch.setattr(TARGET, fail)

    with pytest.raises(HTTPError):
        Fake().get_price("FPT")
