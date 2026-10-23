import time
from datetime import datetime
from urllib.error import HTTPError

from .base import VN_TZ, Price, PriceNotFoundError, PriceSource, http_get_json, validate_symbol


class DNSE(PriceSource):
    name = "DNSE"

    def get_latest_price(self, symbol: str) -> Price:
        symbol = validate_symbol(symbol)
        now = int(time.time())
        try:
            d = http_get_json(
                "https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"
                f"?from={now - 86400 * 10}&to={now}&symbol={symbol}&resolution=1D"
            )
        except HTTPError as e:
            if e.code in (400, 404):  # DNSE answers 400 for a ticker it does not know
                raise PriceNotFoundError(f"no data for {symbol} (HTTP {e.code})") from e
            raise
        if not d.get("t"):
            raise PriceNotFoundError(f"no data for {symbol} (unknown ticker?)")
        return Price(
            symbol=symbol,
            source=self.name,
            date=datetime.fromtimestamp(d["t"][-1], VN_TZ).date(),
            open=d["o"][-1],
            high=d["h"][-1],
            low=d["l"][-1],
            close=d["c"][-1],
            volume=d["v"][-1],
        )
