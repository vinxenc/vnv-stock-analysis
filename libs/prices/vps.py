import time

from .base import Prices, PriceSource, http_get_json, tradingview_last


class VPS(PriceSource):
    name = "VPS"

    def get_price(self, symbol: str) -> Prices:
        symbol = symbol.upper()
        now = int(time.time())
        d = http_get_json(
            "https://histdatafeed.vps.com.vn/tradingview/history"
            f"?symbol={symbol}&resolution=1D&from={now - 86400 * 10}&to={now}"
        )
        return tradingview_last(self.name, symbol, d)
