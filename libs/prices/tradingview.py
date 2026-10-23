import time
from abc import abstractmethod
from datetime import datetime
from urllib.error import HTTPError

from .base import VN_TZ, Price, PriceNotFoundError, PriceSource, http_get_json, validate_symbol

LOOKBACK_SECONDS = 86400 * 10


def tradingview_last(source: str, symbol: str, d: dict) -> Price:
    """DNSE and VPS share the TradingView-style layout: parallel arrays t/o/h/l/c/v."""
    if not d.get("t"):
        raise PriceNotFoundError(f"no data for {symbol} (unknown ticker?)")
    return Price(
        symbol=symbol,
        source=source,
        date=datetime.fromtimestamp(d["t"][-1], VN_TZ).date(),
        open=d["o"][-1],
        high=d["h"][-1],
        low=d["l"][-1],
        close=d["c"][-1],
        volume=d["v"][-1],
    )


class TradingViewSource(PriceSource):
    """Base for sources that serve TradingView-style daily history; subclasses only build the URL."""

    @abstractmethod
    def url(self, symbol: str, start: int, end: int) -> str:
        """History URL for `symbol` between the unix timestamps `start` and `end`."""

    def get_latest_price(self, symbol: str) -> Price:
        symbol = validate_symbol(symbol)
        now = int(time.time())
        try:
            d = http_get_json(self.url(symbol, now - LOOKBACK_SECONDS, now))
        except HTTPError as e:
            if e.code in (400, 404):  # DNSE answers 400 for a ticker it does not know
                raise PriceNotFoundError(f"no data for {symbol} (HTTP {e.code})") from e
            raise
        return tradingview_last(self.name, symbol, d)
