import time
from datetime import datetime

from .base import VN_TZ, Price, PriceNotFoundError, PriceSource, http_get_json, validate_symbol


class VPS(PriceSource):
    name = "VPS"

    def get_latest_price(self, symbol: str) -> Price:
        symbol = validate_symbol(symbol)
        now = int(time.time())
        data = http_get_json(
            "https://histdatafeed.vps.com.vn/tradingview/history"
            f"?symbol={symbol}&resolution=1D&from={now - 86400 * 10}&to={now}"
        )
        if not data.get("t"):
            raise PriceNotFoundError(f"no data for {symbol} (unknown ticker?)")
        return Price.model_validate(
            dict(
                symbol=symbol,
                source=self.name,
                date=datetime.fromtimestamp(data["t"][-1], VN_TZ).date(),
                open=data["o"][-1],
                high=data["h"][-1],
                low=data["l"][-1],
                close=data["c"][-1],
                volume=data["v"][-1],
            )
        )
