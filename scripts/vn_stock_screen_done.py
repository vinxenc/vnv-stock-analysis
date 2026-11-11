"""Record the session the screen did in `vn_stock_screen_history`: run it after the analysis succeeded.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_screen_done [session_file]
Default: out/screen_session.txt (written by vn_stock_screen, one ISO date)
Until this runs the session stays due, so a run that failed after the screen is redone by the next one. Recording a
session twice (two overlapping runs) is harmless. Exit 0 = recorded, anything else = crash.
"""

import datetime as dt
import sys
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from libs.db import connect
from libs.db.models import ScreenHistory
from libs.logger import Logger, LogxideLogger

logger = LogxideLogger("vn_stock_screen_done")


def main(
    session_file: Path = Path("out/screen_session.txt"), engine: Engine | None = None, log: Logger = logger
) -> int:
    day = dt.date.fromisoformat(session_file.read_text(encoding="utf-8").strip())
    with (engine or connect()).begin() as connection:
        connection.execute(insert(ScreenHistory).values(date=day).on_conflict_do_nothing())
    log.info("recorded the session %s", day)
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
