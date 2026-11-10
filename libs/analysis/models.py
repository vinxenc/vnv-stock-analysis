"""The output contract of `vn_stock_analyze` (`out/vn_stock_analysis.json`). Phase 2 reads it: keep it stable.

Plain pydantic models, no database. Dates and every other non-number inside `raw` are strings (JSON).
"""

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

RawValue = float | int | str | None


class Theme(StrEnum):
    TREND = "trend"
    MOMENTUM = "momentum"
    MONEY_FLOW = "money_flow"
    POSITION = "position"
    RISK = "risk"
    REVERSAL = "reversal"


class IndicatorStatus(StrEnum):
    SCORED = "scored"
    GATE_CLOSED = "gate_closed"  # a gate decided it counts for nothing today: 0 points, but available
    UNAVAILABLE = "unavailable"  # too few rows or no value: 0 points, not counted in the coverage


class Flag(StrEnum):
    """Shown next to the score; never changes it."""

    CEILING_LOCKED = "ceiling_locked"  # close within 0.5% of the +7% ceiling: hard to buy
    NEW_LISTING = "new_listing"
    LOW_COVERAGE = "low_coverage"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class IndicatorResult(Model):
    id: int = Field(ge=1, le=24)
    theme: Theme
    status: IndicatorStatus
    points: float = Field(ge=0)
    max_points: float = Field(gt=0)
    raw: dict[str, RawValue] = {}  # the numbers behind the points, so the ranking is never a black box


class SymbolResult(Model):
    symbol: str
    score: float | None = Field(ge=0, le=100)  # None = insufficient data: the coverage gate failed, no score
    coverage: float = Field(ge=0, le=100)  # points of the indicators that were available
    turnover: float = Field(ge=0)  # average close × volume over 20 sessions, thousand VND: the ranking tie-break
    themes: dict[Theme, float]  # points per theme
    indicators: list[IndicatorResult]
    flags: list[Flag] = []


class AnalysisReport(Model):
    as_of: dt.date  # the session analysed: the newest date in the history
    universe_size: int = Field(ge=0)  # symbols in data/hose_symbols.csv; the shortlist is len(symbols)
    sources: list[str]  # price sources found in the history, e.g. ["DNSE", "VNDirect"]
    symbols: list[SymbolResult]  # ranked: score descending, ties by turnover, symbols without a score last
