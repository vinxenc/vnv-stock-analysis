from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from libs.db import connect


def test_migrations_roundtrip_and_match_the_models(alembic_config: Config) -> None:
    """upgrade head, downgrade to nothing, upgrade head again, then no drift between the models and the migrations."""
    command.downgrade(alembic_config, "base")
    engine = connect()
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)
    assert {index["name"] for index in inspect(engine).get_indexes("prices")} == {"ix_prices_date"}
    engine.dispose()
