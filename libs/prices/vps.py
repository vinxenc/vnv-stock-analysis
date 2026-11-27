import time
from datetime import date

from .base import Price, PriceNotFoundError, PriceSource, bars, http_get_json, span, validate_symbol


class VPS(PriceSource):
    name = "VPS"

    def get_latest_price(self, symbol: str) -> Price:
        now = int(time.time())
        recent = self._bars(symbol, now - 86400 * 10, now)
        if not recent:
            raise PriceNotFoundError(f"no data for {symbol} (unknown ticker?)")
        return recent[-1]

    def get_history(self, symbol: str, start: date, end: date) -> list[Price]:
        return self._bars(symbol, *span(start, end))

    def _bars(self, symbol: str, start: int, end: int) -> list[Price]:
        symbol = validate_symbol(symbol)
        data = http_get_json(
            f"https://histdatafeed.vps.com.vn/tradingview/history?symbol={symbol}&resolution=1D&from={start}&to={end}"
        )
        return bars(self.name, symbol, data)
