import time

import niquests

from .base import Price, PriceNotFoundError, PriceSource, bars, http_get_json, validate_symbol


class DNSE(PriceSource):
    name = "DNSE"

    def get_latest_price(self, symbol: str) -> Price:
        return self.get_recent_prices(symbol)[-1]

    def get_recent_prices(self, symbol: str) -> list[Price]:
        """The sessions of the last 10 calendar days."""
        symbol = validate_symbol(symbol)
        now = int(time.time())
        try:
            data = http_get_json(
                "https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"
                f"?from={now - 86400 * 10}&to={now}&symbol={symbol}&resolution=1D"
            )
        except niquests.HTTPError as error:
            code = error.response.status_code
            if code in (400, 404):  # DNSE answers 400 for a ticker it does not know
                raise PriceNotFoundError(f"no data for {symbol} (HTTP {code})") from error
            raise
        if not data.get("t"):
            raise PriceNotFoundError(f"no data for {symbol} (unknown ticker?)")
        return bars(self.name, symbol, data)
