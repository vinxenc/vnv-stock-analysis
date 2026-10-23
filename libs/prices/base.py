import json
import urllib.request
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
VN_TZ = timezone(timedelta(hours=7))


class Prices(BaseModel):
    """Latest daily OHLCV of one stock. Prices are in thousand VND."""

    symbol: str
    source: str
    unit: str = "thousand VND"
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class PriceSource(ABC):
    name: str

    @abstractmethod
    def get_price(self, symbol: str) -> Prices:
        """Latest daily price of `symbol`. Raises on HTTP errors or unknown ticker."""


def http_get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return json.load(r)


def tradingview_last(source: str, symbol: str, d: dict) -> Prices:
    """DNSE and VPS share the TradingView-style layout: parallel arrays t/o/h/l/c/v."""
    if not d.get("t"):
        raise ValueError(f"no data for {symbol} (unknown ticker?)")
    return Prices(
        symbol=symbol,
        source=source,
        date=datetime.fromtimestamp(d["t"][-1], VN_TZ).date(),
        open=d["o"][-1],
        high=d["h"][-1],
        low=d["l"][-1],
        close=d["c"][-1],
        volume=d["v"][-1],
    )
