import time
from datetime import datetime

import niquests

from libs.constants import VN_TZ

from .base import Price, PriceNotFoundError, PriceSource, http_get_json, validate_symbol


class DNSE(PriceSource):
    name = "DNSE"

    def get_latest_price(self, symbol: str) -> Price:
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
