import datetime as dt
from typing import Self

from pydantic import ConfigDict, model_validator
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
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def check_range(self) -> Self:
        # 0.01 slack: adjusted prices are rounded per field, so open/close may poke out of low/high by a hair
        if self.low > self.high or not (
            self.low - 0.01 <= min(self.open, self.close) and max(self.open, self.close) <= self.high + 0.01
        ):
            raise ValueError(f"inconsistent OHLC: {self.open=} {self.high=} {self.low=} {self.close=}")
        return self


class Price(PriceBase, table=True):
    """One row per stock per day."""

    __tablename__ = "prices"

    symbol: str = Field(primary_key=True)
    date: dt.date = Field(primary_key=True)
