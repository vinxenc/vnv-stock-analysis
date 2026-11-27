import re
from abc import ABC, abstractmethod
from datetime import date, datetime, time
from typing import Any

import niquests
from pydantic import ValidationError

from libs.constants import VN_TZ
from libs.db.models import Price

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
SYMBOL_RE = re.compile(r"[A-Z0-9]{1,10}")


class PriceNotFoundError(ValueError):
    """The ticker is invalid or the source has no data for it."""


class PriceSource(ABC):
    name: str

    @abstractmethod
    def get_latest_price(self, symbol: str) -> Price:
        """Latest daily price of `symbol`.

        Raises PriceNotFoundError for an invalid or unknown ticker. Other failures
        (network, HTTP 5xx, malformed payload) propagate as their own exceptions.
        """

    def get_history(self, symbol: str, start: date, end: date) -> list[Price]:
        """Every daily bar from `start` to `end` (both included), ascending, adjusted as of today like the latest one.
        Empty when the symbol had no session then (not listed yet). Only the chart sources (DNSE, VPS) have it."""
        raise NotImplementedError(f"{self.name} has no history")


def span(start: date, end: date) -> tuple[int, int]:
    """`start` 00:00 to `end` 23:59:59 in Vietnam time, as the unix seconds of a chart request."""
    return int(datetime.combine(start, time.min, VN_TZ).timestamp()), int(
        datetime.combine(end, time.max, VN_TZ).timestamp()
    )


def bars(source: str, symbol: str, data: dict[str, Any]) -> list[Price]:
    """The `t/o/h/l/c/v` arrays of a TradingView-style chart payload (DNSE, VPS) as prices, ascending; none when the
    payload has no bar. An invalid bar (a price of 0, say) is dropped, except the latest one; one bar per date."""
    if not data.get("t"):
        return []
    *older, latest = zip(data["t"], data["o"], data["h"], data["l"], data["c"], data["v"], strict=True)

    def price(t: int, o: float, h: float, low: float, c: float, v: int) -> Price:
        day = datetime.fromtimestamp(t, VN_TZ).date()
        return Price.model_validate(
            dict(symbol=symbol, source=source, date=day, open=o, high=h, low=low, close=c, volume=v)
        )

    valid = []
    for row in older:
        try:
            valid.append(price(*row))
        except ValidationError:
            continue
    # DNSE has two bars for some dates (2022-12-27: a stray 07:00 one before the 09:00 session): the later one wins
    return list({bar.date: bar for bar in [*valid, price(*latest)]}.values())


def validate_symbol(symbol: str) -> str:
    """Normalise to upper case and reject anything that is not a plain ticker (it goes into URLs)."""
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise PriceNotFoundError(f"invalid symbol {symbol!r}")
    return symbol


def http_get_json(url: str) -> dict[str, Any]:
    result = niquests.get(url, headers=UA, timeout=15)
    result.raise_for_status()
    return result.json()
