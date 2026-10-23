import json
import re
import urllib.request
from abc import ABC, abstractmethod
from datetime import date, timedelta, timezone
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
VN_TZ = timezone(timedelta(hours=7))
SYMBOL_RE = re.compile(r"[A-Z0-9]{1,10}")


class PriceNotFoundError(ValueError):
    """The ticker is invalid or the source has no data for it."""


class Price(BaseModel):
    """Latest daily OHLCV of one stock. Prices are in thousand VND."""

    symbol: str
    source: str
    unit: str = "thousand VND"
    date: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def check_range(self) -> Self:
        # 0.01 slack: adjusted prices are rounded per field, so open/close may poke out of low/high by a hair
        if not (self.low - 0.01 <= min(self.open, self.close) and max(self.open, self.close) <= self.high + 0.01):
            raise ValueError(f"inconsistent OHLC: {self.open=} {self.high=} {self.low=} {self.close=}")
        return self


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
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return json.load(r)
