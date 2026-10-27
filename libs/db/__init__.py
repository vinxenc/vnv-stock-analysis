import os
import re


def database_url() -> str:
    """$DATABASE_URL for SQLAlchemy + psycopg 3. Hosts hand out `postgres://`, which SQLAlchemy cannot load."""
    return re.sub(r"^postgres(ql)?(\+psycopg)?://", "postgresql+psycopg://", os.environ["DATABASE_URL"])
