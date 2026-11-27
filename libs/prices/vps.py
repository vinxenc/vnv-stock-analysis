from datetime import date

from .base import Price, PriceSource, bars, http_get_json, span, validate_symbol


class VPS(PriceSource):
    name = "VPS"

    def get_history(self, symbol: str, start: date, end: date) -> list[Price]:
        symbol = validate_symbol(symbol)
        first, last = span(start, end)
        data = http_get_json(
            f"https://histdatafeed.vps.com.vn/tradingview/history?symbol={symbol}&resolution=1D&from={first}&to={last}"
        )
        return bars(self.name, symbol, data)
