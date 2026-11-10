"""History in, ranked `AnalysisReport` out: score every symbol, apply the gates, rank. No I/O."""

import datetime as dt

from libs.analysis import gates, scoring
from libs.analysis.features import Candles, mean
from libs.analysis.models import AnalysisReport, IndicatorResult, SymbolResult, Theme
from libs.db.models import Price
from libs.indicators import Indicators

History = dict[str, list[Price]]  # symbol -> rows ascending by date, the last row being the session analysed
TURNOVER_SESSIONS = 20  # the ranking tie-break, same average as the liquidity screen


def symbol_result(
    symbol: str, candles: Candles, indicators: list[IndicatorResult], listed_date: dt.date, as_of: dt.date
) -> SymbolResult:
    available = gates.available_points(indicators)
    points = sum(item.points for item in indicators)
    turnover = mean(
        [close * volume for close, volume in zip(candles.close, candles.volume, strict=True)][-TURNOVER_SESSIONS:]
    )
    previous_close = candles.close[-2] if len(candles) > 1 else candles.close[-1]
    return SymbolResult(
        symbol=symbol,
        score=round(points, 2) if gates.is_scored(available) else None,
        coverage=available,
        turnover=turnover,
        themes={theme: round(sum(i.points for i in indicators if i.theme == theme), 2) for theme in Theme},
        indicators=indicators,
        flags=gates.flags(candles.close[-1], previous_close, listed_date, as_of, available),
    )


def rank(results: list[SymbolResult]) -> list[SymbolResult]:
    """Score descending, ties by turnover descending; the symbols without a score come last, by turnover."""
    return sorted(results, key=lambda result: (result.score is None, -(result.score or 0), -result.turnover))


def build_report(history: History, listed_dates: dict[str, dt.date], engine: Indicators) -> AnalysisReport:
    """`listed_dates` is every symbol of the universe (data/hose_symbols.csv); the history is the shortlist."""
    candles = {symbol: Candles.from_prices(rows) for symbol, rows in history.items()}
    raws = {symbol: scoring.raw_values(item, engine) for symbol, item in candles.items()}
    ranks = scoring.percentile_ranks(raws)
    as_of = max(rows[-1].date for rows in history.values())
    results = rank(
        [
            symbol_result(
                symbol,
                candles[symbol],
                scoring.score_indicators(raws[symbol], ranks[symbol]),
                listed_dates[symbol],
                as_of,
            )
            for symbol in history
        ]
    )
    return AnalysisReport(
        as_of=as_of,
        universe_size=len(listed_dates),
        sources=sorted({rows[-1].source for rows in history.values()}),
        symbols=results,
    )
