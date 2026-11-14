"""The day's candidates: the symbols the deciders answer for (Phase 2). Plain pydantic models and files, no database.

The filter job (`scripts/vn_stock_decision_filter.py`) builds `DecisionInput` from the analysis of the day and the price
history of the same run, writes it as one JSON file, and the decide and notify jobs read it back.
"""

import datetime as dt
import json
from pathlib import Path

from libs.analysis.models import AnalysisReport, Model, SymbolResult

MIN_SCORE = 40  # a symbol is a candidate from this score (inclusive) up; the same for the three deciders
BARS = 60  # the last sessions of price history given to a decider with each symbol


class Bar(Model):
    """One daily bar, prices in thousand VND."""

    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int


class Candidate(SymbolResult):
    """A symbol of the analysis with its recent bars, ascending by date, the last one on or before the session."""

    bars: list[Bar]


class DecisionInput(Model):
    """The file the filter job writes: the session decided and its candidates, in the report's ranking order."""

    session: dt.date
    symbols: list[Candidate]


def read_bars(path: Path) -> list[Bar]:
    """The rows of one `<SYMBOL>.json` of the history (what `vn_stock_get_history` wrote), as bars."""
    return [Bar.model_validate(_bar_fields(row)) for row in json.loads(path.read_text(encoding="utf-8"))]


def _bar_fields(row: dict) -> dict:
    """A history row also has `symbol`, `source` and `unit`, which a bar does not keep."""
    return {key: row[key] for key in Bar.model_fields}


def build_input(
    report: AnalysisReport, history_dir: Path, *, min_score: float = MIN_SCORE, bars: int = BARS
) -> DecisionInput:
    """The symbols of `report` scored `min_score` or more, in the report's order, each with its last `bars` bars up to
    the session (`report.as_of`), never after. A symbol without a score (insufficient data) is never a candidate. Every
    candidate must have its history file: the analysis was computed from the same directory."""
    candidates = []
    for result in report.symbols:
        if result.score is None or result.score < min_score:
            continue
        history = [bar for bar in read_bars(history_dir / f"{result.symbol}.json") if bar.date <= report.as_of]
        candidates.append(Candidate(**result.model_dump(), bars=history[-bars:]))
    return DecisionInput(session=report.as_of, symbols=candidates)


def write_input(data: DecisionInput, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.model_dump_json(indent=1), encoding="utf-8")


def read_input(path: Path) -> DecisionInput:
    return DecisionInput.model_validate_json(path.read_text(encoding="utf-8"))
