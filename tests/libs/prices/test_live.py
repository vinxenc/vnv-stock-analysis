import contextlib
from datetime import date, timedelta

import pytest

from libs.prices import DNSE, VPS, PriceNotFoundError, PriceSource, VNDirect

pytestmark = pytest.mark.live

SOURCES = [DNSE, VPS, VNDirect]
RECENT = (date.today() - timedelta(days=10), date.today())


@pytest.mark.parametrize("cls", SOURCES)
def test_live_fpt(cls: type[PriceSource]) -> None:
    bars = cls().get_history("FPT", *RECENT)

    assert bars and [bar.date for bar in bars] == sorted({bar.date for bar in bars})
    assert all(RECENT[0] <= bar.date <= RECENT[1] for bar in bars)
    price = bars[-1]
    assert price.symbol == "FPT" and price.source == cls.name
    assert 0 < price.low <= price.close <= price.high
    assert price.volume > 0


@pytest.mark.parametrize("cls", SOURCES)
def test_live_unknown_ticker(cls: type[PriceSource]) -> None:
    """No bar, or refused (DNSE answers 400)."""
    with contextlib.suppress(PriceNotFoundError):
        assert cls().get_history("ZZZZZZ", *RECENT) == []
