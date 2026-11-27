from datetime import date

import pytest

from libs.prices import Price, PriceNotFoundError, PriceSource, VNDirect

TARGET = "libs.prices.vndirect.http_get_json"

PAYLOAD = {
    "data": [
        {
            "date": "2026-10-23",
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,  # raw prices must be ignored
            "adOpen": 57.2,
            "adHigh": 57.2,
            "adLow": 56.6,
            "adClose": 57.0,
            "nmVolume": 7090600.0,
        }
    ]
}


def test_get_latest_price_uses_adjusted_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []
    monkeypatch.setattr(TARGET, lambda url: urls.append(url) or PAYLOAD)
    source = VNDirect()

    price = source.get_latest_price("fpt")

    assert isinstance(source, PriceSource)
    assert price == Price.model_validate(
        dict(
            symbol="FPT",
            source="VNDirect",
            date=date(2026, 10, 23),
            open=57.2,
            high=57.2,
            low=56.6,
            close=57.0,
            volume=7090600,
        )
    )
    assert "code:FPT&" in urls[0]  # symbol upper-cased in the request


def test_unknown_ticker_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TARGET, lambda url: {"data": []})

    with pytest.raises(PriceNotFoundError, match="ZZZ"):
        VNDirect().get_latest_price("ZZZ")


def test_invalid_symbol_rejected_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str) -> dict:
        raise AssertionError("request must not be made")

    monkeypatch.setattr(TARGET, boom)

    with pytest.raises(PriceNotFoundError, match="invalid symbol"):
        VNDirect().get_latest_price("FPT~floor:HOSE")


def test_get_ex_rights(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []
    rows = [{"code": "FPT", "type": "DIVIDEND"}, {"code": "VPX", "type": "KINDDIV"}, {"code": "FPT", "type": "ISSUE"}]
    monkeypatch.setattr(TARGET, lambda url: urls.append(url) or {"data": rows})
    assert VNDirect().get_ex_rights(date(2026, 11, 27)) == {"FPT", "VPX"}
    assert "q=effectiveDate:2026-11-27~type:DIVIDEND,STOCKDIV,KINDDIV,ISSUE~locale:VN&" in urls[0]


def test_vndirect_has_no_history() -> None:
    with pytest.raises(NotImplementedError):
        VNDirect().get_history("FPT", date(2019, 1, 1), date(2019, 12, 31))
