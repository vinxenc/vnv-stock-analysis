from .base import Prices, PriceSource, http_get_json


class VNDirect(PriceSource):
    name = "VNDirect"

    def get_price(self, symbol: str) -> Prices:
        symbol = symbol.upper()
        rows = http_get_json(
            f"https://api-finfo.vndirect.com.vn/v4/stock_prices?sort=date:desc&q=code:{symbol}&size=1"
        )["data"]
        if not rows:
            raise ValueError(f"no data for {symbol} (unknown ticker?)")
        r = rows[0]
        # ad* = adjusted for dividends/splits, matching DNSE and VPS; plain open/close are raw
        return Prices(
            symbol=symbol,
            source=self.name,
            date=r["date"],
            open=r["adOpen"],
            high=r["adHigh"],
            low=r["adLow"],
            close=r["adClose"],
            volume=r["nmVolume"],
        )
