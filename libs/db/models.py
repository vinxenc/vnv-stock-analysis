import datetime as dt

from pydantic import ConfigDict
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Enum, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from libs.analysis.models import Timeframe
from libs.decision.models import Decider, Verdict


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


def _one_of(column: str, values: type[Decider] | type[Verdict]) -> str:
    return f"{column} IN ({', '.join(repr(value.value) for value in values)})"


class DecisionRecord(SQLModel, table=True):
    """One answer of one decider about one symbol of one session (buy or skip, with the probability of buy), and
    its outcome five sessions later. A decider's rows for a session are replaced by its latest run. `decider` and
    `decision` are text with a CHECK on `Decider` and `Verdict`, `probability` has one between 0 and 1 (`CLAUDE.md`:
    `alembic check` does not compare CHECK constraints, so a test tries a bad value)."""

    __tablename__ = "vn_stock_decisions"
    __table_args__ = (
        CheckConstraint(_one_of("decider", Decider), name="ck_vn_stock_decisions_decider"),
        CheckConstraint(_one_of("decision", Verdict), name="ck_vn_stock_decisions_decision"),
        CheckConstraint("probability BETWEEN 0 AND 1", name="ck_vn_stock_decisions_probability"),
    )

    date: dt.date = Field(primary_key=True)  # the session decided (`t`)
    symbol: str = Field(primary_key=True)
    decider: str = Field(primary_key=True, sa_type=Text)
    decision: str = Field(sa_type=Text)
    probability: float  # of buy
    reason: str | None = Field(default=None, sa_type=Text)  # Claude only
    model_version: str
    input: dict = Field(sa_type=JSONB)  # the exact input, so any answer can be re-read
    # set by Postgres, never by the code; the ORM leaves a None out of the INSERT
    created_at: dt.datetime | None = Field(
        default=None, nullable=False, sa_type=DateTime(timezone=True), sa_column_kwargs={"server_default": func.now()}
    )
    return_5: float | None = None  # close(t+5) / close(t) - 1, null until the outcome job fills it
    hit: bool | None = None  # return_5 >= 3%
