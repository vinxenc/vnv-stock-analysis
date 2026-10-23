import pytest

from libs.prices import DNSE, VPS, PriceNotFoundError, PriceSource, VNDirect

pytestmark = pytest.mark.live

SOURCES = [DNSE, VPS, VNDirect]


@pytest.mark.parametrize("cls", SOURCES)
def test_live_fpt(cls: type[PriceSource]) -> None:
    price = cls().get_latest_price("FPT")

    assert price.symbol == "FPT" and price.source == cls.name
    assert 0 < price.low <= price.close <= price.high
    assert price.volume > 0


@pytest.mark.parametrize("cls", SOURCES)
def test_live_unknown_ticker(cls: type[PriceSource]) -> None:
    with pytest.raises(PriceNotFoundError):
        cls().get_latest_price("ZZZZZZ")
