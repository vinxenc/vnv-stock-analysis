import pytest

from libs.prices import DNSE, VPS, PriceSource, VNDirect

pytestmark = pytest.mark.live


@pytest.mark.parametrize("cls", [DNSE, VPS, VNDirect])
def test_live_fpt(cls: type[PriceSource]) -> None:
    price = cls().get_price("FPT")

    assert price.symbol == "FPT" and price.source == cls.name
    assert 0 < price.low <= price.close <= price.high
    assert price.volume > 0
