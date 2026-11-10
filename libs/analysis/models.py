"""The output contract of `vn_stock_analyze` (`out/vn_stock_analysis.json`). Phase 2 reads it: keep it stable.

Plain pydantic models, no database. Dates and every other non-number inside `raw` are strings (JSON).
"""

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    UNAVAILABLE = "unavailable"  # not enough rows or a corrupted window: 0 points, not counted in the coverage


class SymbolStatus(StrEnum):
    SCORED = "scored"
    INSUFFICIENT_DATA = "insufficient data"  # coverage gate failed: no score


class Flag(StrEnum):
    """Shown next to the score; never changes it."""

    CEILING_LOCKED = "ceiling_locked"  # close within 0.5% of the +7% ceiling: hard to buy
    NEW_LISTING = "new_listing"
    SUSPECTED_CORPORATE_ACTION = "suspected_corporate_action"
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

    @model_validator(mode="after")
    def check_points(self) -> "IndicatorResult":
        if self.points > self.max_points:
            raise ValueError(f"indicator {self.id}: {self.points} points above the maximum {self.max_points}")
        if self.status != IndicatorStatus.SCORED and self.points != 0:
            raise ValueError(f"indicator {self.id}: {self.status} must have 0 points")
        return self


class SymbolResult(Model):
    symbol: str
    status: SymbolStatus
    score: float | None = Field(ge=0, le=100)  # None exactly when the status is "insufficient data"
    coverage: float = Field(ge=0, le=100)  # points of the indicators that were available
    turnover: float = Field(ge=0)  # average close × volume over 20 sessions, thousand VND: the ranking tie-break
    themes: dict[Theme, float]  # points per theme
    indicators: list[IndicatorResult]
    flags: list[Flag] = []

    @model_validator(mode="after")
    def check_score(self) -> "SymbolResult":
        if (self.score is None) != (self.status == SymbolStatus.INSUFFICIENT_DATA):
            raise ValueError(f"{self.symbol}: score {self.score} does not match the status {self.status}")
        return self


class AnalysisReport(Model):
    as_of: dt.date  # the session analysed (today, VN)
    universe_size: int = Field(ge=0)  # symbols in data/hose_symbols.csv
    shortlist_size: int = Field(ge=0)  # symbols that passed the liquidity screen
    scored: int = Field(ge=0)
    insufficient_data: int = Field(ge=0)
    flagged: int = Field(ge=0)  # symbols with at least one flag
    missing_previous_session: list[str] = []  # on the shortlist but without a bar on the preceding session
    sources: list[str]  # price sources found in the history, e.g. ["DNSE", "VNDirect"]
    symbols: list[SymbolResult]  # ranked: score descending, ties by turnover, "insufficient data" last

    @model_validator(mode="after")
    def check_counts(self) -> "AnalysisReport":
        scored = sum(symbol.status == SymbolStatus.SCORED for symbol in self.symbols)
        flagged = sum(bool(symbol.flags) for symbol in self.symbols)
        counts = (self.scored, self.insufficient_data, self.flagged)
        if counts != (scored, len(self.symbols) - scored, flagged):
            raise ValueError(f"counts {counts} do not match the symbols")
        if self.shortlist_size != len(self.symbols) + len(self.missing_previous_session):
            raise ValueError("shortlist_size is not the symbols plus the missing_previous_session list")
        return self
