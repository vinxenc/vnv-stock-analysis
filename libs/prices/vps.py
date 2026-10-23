from .tradingview import TradingViewSource


class VPS(TradingViewSource):
    name = "VPS"

    def url(self, symbol: str, start: int, end: int) -> str:
        return (
            "https://histdatafeed.vps.com.vn/tradingview/history"
            f"?symbol={symbol}&resolution=1D&from={start}&to={end}"
        )
