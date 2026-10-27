import re
from abc import ABC, abstractmethod
from datetime import timedelta, timezone
from typing import Any

import niquests

from libs.db.models import PriceBase as Price  # the validated, non-table model; defined in libs/db

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
VN_TZ = timezone(timedelta(hours=7))
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
