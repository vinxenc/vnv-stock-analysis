import datetime as dt

from pydantic import ConfigDict
from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class PriceBase(SQLModel):
    """Latest daily OHLCV of one stock, validated. Prices are in thousand VND.

    Not a table: SQLModel skips validation when a `table=True` class is built, so retrieval and an API use this one.
    """

    model_config = ConfigDict(allow_inf_nan=False)

    symbol: str
    source: str
    unit: str = "thousand VND"
    date: dt.date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0, sa_type=BigInteger)  # daily volume can pass 2^31


class Price(PriceBase, table=True):
    """One row per stock per day. Building this class does not validate: check the data with `PriceBase` first."""

    __tablename__ = "prices"

    symbol: str = Field(primary_key=True)
    date: dt.date = Field(primary_key=True)
