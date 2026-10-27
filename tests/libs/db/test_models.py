from libs.db import models


def test_price_table_layout() -> None:
    table = models.Price.__table__
    assert table.name == "daily_prices"
    assert [column.name for column in table.primary_key.columns] == ["symbol", "date"]
    assert {"open", "high", "low", "close", "volume", "source", "unit", "fetched_at"} <= set(table.columns.keys())
