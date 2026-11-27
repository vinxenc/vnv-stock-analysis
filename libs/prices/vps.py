import time

from .base import Price, PriceNotFoundError, PriceSource, bars, http_get_json, validate_symbol


class VPS(PriceSource):
    name = "VPS"

    def get_latest_price(self, symbol: str) -> Price:
        return self.get_recent_prices(symbol)[-1]

    def get_recent_prices(self, symbol: str) -> list[Price]:
        """The sessions of the last 10 calendar days."""
        symbol = validate_symbol(symbol)
        now = int(time.time())
        data = http_get_json(
            "https://histdatafeed.vps.com.vn/tradingview/history"
            f"?symbol={symbol}&resolution=1D&from={now - 86400 * 10}&to={now}"
        )
        if not data.get("t"):
            raise PriceNotFoundError(f"no data for {symbol} (unknown ticker?)")
        return bars(self.name, symbol, data)
