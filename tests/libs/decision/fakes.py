import datetime as dt
import json
from pathlib import Path

from libs.analysis.models import AnalysisReport, IndicatorResult, IndicatorStatus, SymbolResult, Theme
from tests.libs.analysis.fakes import make_rows

DAY = dt.date(2026, 11, 10)


def result(code: str, score: float | None) -> SymbolResult:
    """A symbol with one indicator, enough to check what is carried to the candidates."""
    indicator = IndicatorResult(
        id=1, theme=Theme.TREND, status=IndicatorStatus.SCORED, points=2.5, max_points=3, raw={"close_vs_sma20": 0.02}
    )
    themes = {theme: 2.5 if theme == Theme.TREND else 0.0 for theme in Theme}
    return SymbolResult(
        symbol=code, score=score, coverage=80, turnover=1e6, themes=themes, indicators=[indicator], flags=[]
    )


def report(*symbols: SymbolResult) -> AnalysisReport:
    """A report of DAY with these symbols, in this order."""
    return AnalysisReport(as_of=DAY, universe_size=406, sources=["DNSE"], symbols=list(symbols))


def write_history(directory: Path, code: str, count: int = 70, end: dt.date = DAY) -> None:
    """`<code>.json` as `vn_stock_get_history` writes it: `count` rows ascending by date, the last on `end`."""
    rows = [row.model_dump(mode="json") for row in make_rows(code, count, end=end)]
    (directory / f"{code}.json").write_text(json.dumps(rows), encoding="utf-8")
