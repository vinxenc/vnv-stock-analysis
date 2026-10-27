import datetime as dt

from sqlalchemy import DateTime, func
from sqlmodel import Field

from libs.prices import Price as PriceData


class Price(PriceData, table=True):
    """One row per stock per day. The validated fields come from `libs.prices.Price`."""

    __tablename__ = "daily_prices"

    symbol: str = Field(primary_key=True)
    date: dt.date = Field(primary_key=True)
    fetched_at: dt.datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), sa_column_kwargs={"server_default": func.now()}
    )
