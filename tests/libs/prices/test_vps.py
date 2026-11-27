from datetime import UTC, date, datetime

import pytest

from libs.prices import VPS, Price, PriceNotFoundError, PriceSource

TARGET = "libs.prices.vps.http_get_json"
OCTOBER = (date(2026, 10, 1), date(2026, 10, 31))


def ts(*args: int) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp())


# two sessions of October 2026
PAYLOAD = {
    "t": [ts(2026, 10, 22, 3), ts(2026, 10, 23, 3)],
    "o": [58.0, 57.2],
    "h": [58.7, 57.2],
    "l": [57.3, 56.6],
    "c": [57.4, 57.0],
    "v": [10088500, 7090600],
}


def test_get_history(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []
    monkeypatch.setattr(TARGET, lambda url: urls.append(url) or PAYLOAD)
    source = VPS()

    bars = source.get_history("fpt", *OCTOBER)

    assert isinstance(source, PriceSource)
    assert bars[-1] == Price.model_validate(
        dict(symbol="FPT", source="VPS", date=date(2026, 10, 23), open=57.2, high=57.2, low=56.6, close=57.0,
             volume=7090600)
    )  # fmt: skip
    assert [bar.date for bar in bars] == [date(2026, 10, 22), date(2026, 10, 23)]
    assert all(OCTOBER[0] <= bar.date <= OCTOBER[1] for bar in bars)
    assert urls[0].startswith("https://histdatafeed.vps.com.vn/") and "symbol=FPT&" in urls[0]
    assert f"from={ts(2026, 9, 30, 17)}&to={ts(2026, 10, 31, 16, 59, 59)}" in urls[0]


def test_date_uses_vietnam_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    # 18:00 UTC on the 22nd is already the 23rd in UTC+7
    data = {"t": [ts(2026, 10, 22, 18)], "o": [1], "h": [1], "l": [1], "c": [1], "v": [1]}
    monkeypatch.setattr(TARGET, lambda url: data)

    assert [bar.date for bar in VPS().get_history("FPT", *OCTOBER)] == [date(2026, 10, 23)]


def test_no_data_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TARGET, lambda url: {"s": "no_data"})
    assert VPS().get_history("ZZZ", *OCTOBER) == []


def test_invalid_symbol_rejected_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str) -> dict:
        raise AssertionError("request must not be made")

    monkeypatch.setattr(TARGET, boom)

    with pytest.raises(PriceNotFoundError, match="invalid symbol"):
        VPS().get_history("FPT&x=1", *OCTOBER)
