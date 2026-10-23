from .tradingview import TradingViewSource


class DNSE(TradingViewSource):
    name = "DNSE"

    def url(self, symbol: str, start: int, end: int) -> str:
        return (
            "https://services.entrade.com.vn/chart-api/v2/ohlcs/stock"
            f"?from={start}&to={end}&symbol={symbol}&resolution=1D"
        )
