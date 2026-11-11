import datetime as dt
from enum import StrEnum

from pydantic import ConfigDict
from sqlalchemy import BigInteger, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Price(SQLModel, table=True):
    """Latest daily OHLCV of one stock, one row per stock per day. Prices are in thousand VND.

    SQLModel skips validation when a `table=True` class is built: create it with `Price.model_validate(data)`, never
    `Price(**data)`.
    """

    __tablename__ = "prices"
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


class Timeframe(StrEnum):
    """The bar size a ranking is computed on. Only daily is computed today; weekly and monthly are reserved."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Ranking(SQLModel, table=True):
    """The ranked shortlist of one screened session, one row per symbol: `out/vn_stock_analysis.json` kept for good
    (the artifact expires after 7 days). Written by `vn_stock_screen_done` with the session's history row."""

    __tablename__ = "vn_stock_rankings"

    date: dt.date = Field(primary_key=True)  # the session analysed (`as_of`)
    # Postgres enum `timeframe`, stored by value ("daily"); adding a value later needs `ALTER TYPE ... ADD VALUE`
    timeframe: Timeframe = Field(
        primary_key=True, sa_type=Enum(Timeframe, name="timeframe", values_callable=lambda e: [m.value for m in e])
    )
    symbol: str = Field(primary_key=True)
    rank: int = Field(ge=1)  # the position in the job summary table; symbols without a score come last
    score: float | None  # None = insufficient data
    coverage: float
    turnover: float  # average close × volume over 20 sessions, thousand VND
    themes: dict[str, float] = Field(sa_type=JSONB)
    flags: list[str] = Field(sa_type=JSONB)
    indicators: list[dict] = Field(sa_type=JSONB)  # the raw numbers behind every point, to tune the thresholds later
