from datetime import date

from .base import Price, PriceSource, http_get_json, validate_symbol

EX_RIGHTS = ("DIVIDEND", "STOCKDIV", "KINDDIV", "ISSUE")  # cash, stock dividend, bonus shares, rights issue


class VNDirect(PriceSource):
    name = "VNDirect"

    def get_history(self, symbol: str, start: date, end: date) -> list[Price]:
        symbol = validate_symbol(symbol)
        rows = http_get_json(
            f"https://api-finfo.vndirect.com.vn/v4/stock_prices?q=code:{symbol}~date:gte:{start}~date:lte:{end}&size=10000"
        )["data"]
        # ad* = adjusted for dividends/splits, matching DNSE and VPS; plain open/close are raw
        prices = [
            Price.model_validate(
                dict(
                    symbol=symbol,
                    source=self.name,
                    date=row["date"],
                    open=row["adOpen"],
                    high=row["adHigh"],
                    low=row["adLow"],
                    close=row["adClose"],
                    volume=row["nmVolume"],
                )
            )
            for row in rows
        ]
        return sorted(prices, key=lambda price: price.date)  # VNDirect may answer in descending order

    def get_ex_rights(self, day: date) -> set[str]:
        """The symbols, of every exchange, whose ex-rights date (GDKHQ) is `day` for an event that moves the price:
        a cash or stock dividend, bonus shares, a rights issue. VNDirect calls the ex-rights date `effectiveDate`."""
        rows = http_get_json(
            f"https://api-finfo.vndirect.com.vn/v4/events?q=effectiveDate:{day.isoformat()}~type:{','.join(EX_RIGHTS)}"
            "~locale:VN&size=1000"
        )["data"]
        return {row["code"] for row in rows}
