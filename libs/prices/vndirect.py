from datetime import date

from .base import Price, PriceNotFoundError, PriceSource, http_get_json, validate_symbol

EX_RIGHTS = ("DIVIDEND", "STOCKDIV", "KINDDIV", "ISSUE")  # cash, stock dividend, bonus shares, rights issue


class VNDirect(PriceSource):
    name = "VNDirect"

    def get_latest_price(self, symbol: str) -> Price:
        rows = self._rows(symbol, "sort=date:desc", "", 1)
        if not rows:
            raise PriceNotFoundError(f"no data for {symbol} (unknown ticker?)")
        return rows[0]

    def get_history(self, symbol: str, start: date, end: date) -> list[Price]:
        return sorted(self._rows(symbol, "sort=date", f"~date:gte:{start}~date:lte:{end}", 10000), key=lambda p: p.date)

    def _rows(self, symbol: str, sort: str, dates: str, size: int) -> list[Price]:
        symbol = validate_symbol(symbol)
        rows = http_get_json(
            f"https://api-finfo.vndirect.com.vn/v4/stock_prices?{sort}&q=code:{symbol}{dates}&size={size}"
        )
        # ad* = adjusted for dividends/splits, matching DNSE and VPS; plain open/close are raw
        return [
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
            for row in rows["data"]
        ]

    def get_ex_rights(self, day: date) -> set[str]:
        """The symbols, of every exchange, whose ex-rights date (GDKHQ) is `day` for an event that moves the price:
        a cash or stock dividend, bonus shares, a rights issue. VNDirect calls the ex-rights date `effectiveDate`."""
        rows = http_get_json(
            f"https://api-finfo.vndirect.com.vn/v4/events?q=effectiveDate:{day.isoformat()}~type:{','.join(EX_RIGHTS)}"
            "~locale:VN&size=1000"
        )["data"]
        return {row["code"] for row in rows}
