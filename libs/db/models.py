import datetime as dt

from pydantic import ConfigDict
from sqlalchemy import BigInteger, Column, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from libs.analysis.models import Timeframe


class Price(SQLModel, table=True):
    """Latest daily OHLCV of one stock, one row per stock per day. Prices are in thousand VND.

    SQLModel skips validation when a `table=True` class is built: create it with `Price.model_validate(data)`, never
    `Price(**data)`.
    """

    __tablename__ = "vn_stock_prices"
    model_config = ConfigDict(allow_inf_nan=False)

    symbol: str = Field(primary_key=True)
    date: dt.date = Field(primary_key=True, index=True)  # the primary key starts with symbol: max(date) needs its own
    source: str
    unit: str = "thousand VND"
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0, sa_type=BigInteger)  # daily volume can pass 2^31


class ScreenHistory(SQLModel, table=True):
    """The sessions `vn_stock_screen` has screened, one row per session. The next run screens the working day after
    the newest one (never `today`: a delayed cron run must not skip or double a session)."""

    __tablename__ = "vn_stock_screen_history"

    date: dt.date = Field(primary_key=True)


class Ranking(SQLModel, table=True):
    """The scores of one screened session, one row per timeframe and symbol: `out/vn_stock_analysis.json` kept for
    good (the artifact expires after 7 days). Upserted by `vn_stock_analyze.store`. No rank column: a rerun can leave
    rows of symbols that left the shortlist, so the order is read from the scores (`score DESC NULLS LAST, turnover
    DESC`)."""

    __tablename__ = "vn_stock_rankings"

    date: dt.date = Field(primary_key=True)  # the session analysed (`as_of`)
    # Postgres enum `timeframe` of the values ("daily"); adding one later needs `ALTER TYPE ... ADD VALUE`
    timeframe: Timeframe = Field(primary_key=True, sa_type=Enum(*Timeframe, name="timeframe"))
    symbol: str = Field(primary_key=True)
    score: float  # above 0: insufficient data (null) and 0 points are not stored
    coverage: float
    turnover: float  # average close × volume over 20 sessions, thousand VND
    themes: dict[str, float] = Field(sa_type=JSONB)
    flags: list[str] = Field(sa_type=JSONB)
    indicators: list[dict] = Field(sa_type=JSONB)  # the raw numbers behind every point, to tune the thresholds later
    # the weights the score was computed with (`scoring.metadata()`); `metadata` is taken by SQLModel, hence `meta`
    meta: dict = Field(sa_column=Column("metadata", JSONB, nullable=False))
