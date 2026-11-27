from datetime import date

import niquests

from .base import Price, PriceNotFoundError, PriceSource, bars, http_get_json, span, validate_symbol


class DNSE(PriceSource):
    name = "DNSE"

    def get_history(self, symbol: str, start: date, end: date) -> list[Price]:
        symbol = validate_symbol(symbol)
        first, last = span(start, end)
        try:
            data = http_get_json(
                "https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"
                f"?from={first}&to={last}&symbol={symbol}&resolution=1D"
            )
        except niquests.HTTPError as error:
            code = error.response.status_code
            if code in (400, 404):  # DNSE answers 400 for a ticker it does not know
                raise PriceNotFoundError(f"no data for {symbol} (HTTP {code})") from error
            raise
        return bars(self.name, symbol, data)
