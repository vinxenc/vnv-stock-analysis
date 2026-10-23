from .base import Price, PriceNotFoundError, PriceSource, http_get_json, validate_symbol


class VNDirect(PriceSource):
    name = "VNDirect"

    def get_latest_price(self, symbol: str) -> Price:
        symbol = validate_symbol(symbol)
        rows = http_get_json(
            f"https://api-finfo.vndirect.com.vn/v4/stock_prices?sort=date:desc&q=code:{symbol}&size=1"
        )["data"]
        if not rows:
            raise PriceNotFoundError(f"no data for {symbol} (unknown ticker?)")
        r = rows[0]
        # ad* = adjusted for dividends/splits, matching DNSE and VPS; plain open/close are raw
        return Price(
            symbol=symbol,
            source=self.name,
            date=r["date"],
            open=r["adOpen"],
            high=r["adHigh"],
            low=r["adLow"],
            close=r["adClose"],
            volume=r["nmVolume"],
        )
