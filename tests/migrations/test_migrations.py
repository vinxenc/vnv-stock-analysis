import csv
import gzip
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from libs.db import connect
from libs.db.models import Price


def test_migrations_roundtrip_and_match_the_models(alembic_config: Config) -> None:
    """upgrade head, downgrade to nothing, upgrade head again, then no drift between the models and the migrations."""
    command.downgrade(alembic_config, "base")
    engine = connect()
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)
    assert set(inspect(engine).get_table_names()) == {"alembic_version", "prices", "vn_stock_screen_history"}
    assert {index["name"] for index in inspect(engine).get_indexes("prices")} == {"ix_prices_date"}
    engine.dispose()


def test_seed_2026_11_09_holds_valid_bars_of_that_day_only() -> None:
    """The seed migration is skipped in the unit tests, so check its frozen file here."""
    with gzip.open("data/seeds/prices_2026_11_09.json.gz", "rt", encoding="utf-8") as file:
        prices = [Price.model_validate(row) for row in json.load(file)]
    listed = {row["code"] for row in csv.DictReader(Path("data/hose_symbols.csv").open(encoding="utf-8"))}
    assert {price.date.isoformat() for price in prices} == {"2026-11-09"}
    assert len({price.symbol for price in prices}) == len(prices)  # one bar per symbol
    assert {price.symbol for price in prices} <= listed
