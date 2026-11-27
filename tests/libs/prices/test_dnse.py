from datetime import UTC, date, datetime

import niquests
import pytest

from libs.prices import DNSE, Price, PriceNotFoundError, PriceSource

TARGET = "libs.prices.dnse.http_get_json"


def ts(*args: int) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp())


def http_error(code: int) -> niquests.HTTPError:
    response = niquests.Response()
    response.status_code = code
    return niquests.HTTPError(response=response)


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
    source = DNSE()

    price = source.get_latest_price("fpt")

    assert isinstance(source, PriceSource)
    assert price == Price.model_validate(
        dict(
            symbol="FPT",
            source="DNSE",
            date=date(2026, 10, 23),
            open=57.2,
            high=57.2,
            low=56.6,
            close=57.0,
            volume=7090600,
        )
    )
    assert urls[0].startswith("https://services.entrade.com.vn/") and "symbol=FPT&" in urls[0]


def test_date_uses_vietnam_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    # 18:00 UTC on the 22nd is already the 23rd in UTC+7
    data = {"t": [ts(2026, 10, 22, 18)], "o": [1], "h": [1], "l": [1], "c": [1], "v": [1]}
    monkeypatch.setattr(TARGET, lambda url: data)

    assert DNSE().get_latest_price("FPT").date == date(2026, 10, 23)


def test_empty_payload_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TARGET, lambda url: {"t": []})

    with pytest.raises(PriceNotFoundError, match="ZZZ"):
        DNSE().get_latest_price("ZZZ")


def test_invalid_symbol_rejected_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str) -> dict:
        raise AssertionError("request must not be made")

    monkeypatch.setattr(TARGET, boom)

    with pytest.raises(PriceNotFoundError, match="invalid symbol"):
        DNSE().get_latest_price("FPT&x=1")


@pytest.mark.parametrize("code", [400, 404])
def test_unknown_ticker_http_errors_become_not_found(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    def fail(url: str) -> dict:
        raise http_error(code)

    monkeypatch.setattr(TARGET, fail)

    with pytest.raises(PriceNotFoundError, match=str(code)):
        DNSE().get_latest_price("ZZZ")


def test_other_http_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(url: str) -> dict:
        raise http_error(503)

    monkeypatch.setattr(TARGET, fail)

    with pytest.raises(niquests.HTTPError):
        DNSE().get_latest_price("FPT")


def test_an_invalid_latest_bar_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TARGET, lambda url: {**PAYLOAD, "c": [57.4, 0]})
    with pytest.raises(ValueError, match="close"):
        DNSE().get_latest_price("FPT")


def test_get_history_asks_for_the_whole_span_in_vietnam_time(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []
    monkeypatch.setattr(TARGET, lambda url: urls.append(url) or PAYLOAD)
    bars = DNSE().get_history("fpt", date(2019, 1, 1), date(2019, 12, 31))
    assert [(bar.date, bar.close) for bar in bars] == [(date(2026, 10, 22), 57.4), (date(2026, 10, 23), 57.0)]
    assert f"from={ts(2018, 12, 31, 17)}&to={ts(2019, 12, 31, 16, 59, 59)}&symbol=FPT&" in urls[0]


def test_get_history_of_a_year_before_the_listing_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TARGET, lambda url: {"t": [], "o": [], "h": [], "l": [], "c": [], "v": []})
    assert DNSE().get_history("FPT", date(2019, 1, 1), date(2019, 12, 31)) == []


def test_an_invalid_older_bar_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TARGET, lambda url: {**PAYLOAD, "c": [0, 57.0]})
    assert [bar.date for bar in DNSE().get_history("FPT", date(2026, 10, 1), date(2026, 10, 31))] == [
        date(2026, 10, 23)
    ]


def test_two_bars_of_one_date_keep_the_later_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """DNSE's 2022-12-27 of FPT: a stray 07:00 bar, then the 09:00 session."""
    data = {"t": [1672099200, 1672106400], "o": [41.64, 41.69], "h": [41.75, 42.26], "l": [41.59, 41.42]}
    monkeypatch.setattr(TARGET, lambda url: {**data, "c": [41.64, 41.69], "v": [123900, 805200]})
    assert [(bar.date, bar.volume) for bar in DNSE().get_history("FPT", date(2022, 12, 1), date(2022, 12, 31))] == [
        (date(2022, 12, 27), 805200)
    ]
