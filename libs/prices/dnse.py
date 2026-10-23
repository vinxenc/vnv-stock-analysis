import time

from .base import Prices, PriceSource, http_get_json, tradingview_last


class DNSE(PriceSource):
    name = "DNSE"

    def get_price(self, symbol: str) -> Prices:
        symbol = symbol.upper()
        now = int(time.time())
        d = http_get_json(
            "https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"
            f"?from={now - 86400 * 10}&to={now}&symbol={symbol}&resolution=1D"
        )
        return tradingview_last(self.name, symbol, d)
