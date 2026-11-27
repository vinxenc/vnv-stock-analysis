import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import niquests

from libs.constants import VN_TZ
from libs.db.models import Price

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
SYMBOL_RE = re.compile(r"[A-Z0-9]{1,10}")


class PriceNotFoundError(ValueError):
    """The ticker is invalid or the source has no data for it."""


class PriceSource(ABC):
    name: str

    @abstractmethod
    def get_latest_price(self, symbol: str) -> Price:
        """Latest daily price of `symbol`.

        Raises PriceNotFoundError for an invalid or unknown ticker. Other failures
        (network, HTTP 5xx, malformed payload) propagate as their own exceptions.
        """

    def get_recent_prices(self, symbol: str) -> list[Price]:
        """The bars the source returns along with the latest one, ascending, the latest last: the price store compares
        the older ones with the stored bars to see a dividend adjustment. Default: the latest bar alone."""
        return [self.get_latest_price(symbol)]


def bars(source: str, symbol: str, data: dict[str, Any]) -> list[Price]:
    """The `t/o/h/l/c/v` arrays of a TradingView-style chart payload (DNSE, VPS) as prices, ascending."""
    return [
        Price.model_validate(
            dict(
                symbol=symbol,
                source=source,
                date=datetime.fromtimestamp(t, VN_TZ).date(),
                open=o,
                high=h,
                low=low,
                close=c,
                volume=v,
            )
        )
        for t, o, h, low, c, v in zip(data["t"], data["o"], data["h"], data["l"], data["c"], data["v"], strict=True)
    ]


def validate_symbol(symbol: str) -> str:
    """Normalise to upper case and reject anything that is not a plain ticker (it goes into URLs)."""
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise PriceNotFoundError(f"invalid symbol {symbol!r}")
    return symbol


def http_get_json(url: str) -> dict[str, Any]:
    result = niquests.get(url, headers=UA, timeout=15)
    result.raise_for_status()
    return result.json()
