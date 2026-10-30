import datetime as dt

from pydantic import ConfigDict
from sqlalchemy import BigInteger
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
