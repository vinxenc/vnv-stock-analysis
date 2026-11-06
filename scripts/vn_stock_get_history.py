"""Read the last SESSIONS sessions of every shortlisted symbol from `prices`, one JSON file per symbol.

Usage: DATABASE_URL=... uv run python -m scripts.vn_stock_get_history [symbols_csv] [output_dir]
Default: out/liquid_symbols.csv (see vn_stock_screen) -> out/vn_stock_history/<SYMBOL>.json
Each file is a JSON array of `Price` rows in ascending date order (the analysis reads them as time series). A symbol
with fewer than SESSIONS rows is logged, never fatal: the analysis decides what to skip. A symbol with no row gets no
file. This job only reads the database. The output directory is emptied first, so it never holds an older run.
Exit 0 = at least one file written, 4 = no row found for any symbol (nothing written), anything else = crash.
"""

import json
import shutil
import sys
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from libs.constants import NO_DATA
from libs.db import connect
from libs.db.models import Price
from libs.logger import Logger, LogxideLogger
from scripts.vn_stock_latest_price_retrieval import read_symbols

SESSIONS = 260  # rows, not calendar days (holidays); the longest lookback of the scoring table is 250 (#17) + a buffer
logger = LogxideLogger("vn_stock_get_history")


def get_history(session: Session, symbol: str) -> list[Price]:
    """The last SESSIONS rows of `symbol`, in ascending date order."""
    newest_first = session.exec(select(Price).where(Price.symbol == symbol).order_by(Price.date.desc()).limit(SESSIONS))
    return list(reversed(newest_first.all()))


def main(
    symbols_csv: Path = Path("out/liquid_symbols.csv"),
    output_dir: Path = Path("out/vn_stock_history"),
    engine: Engine | None = None,
    log: Logger = logger,
) -> int:
    shutil.rmtree(output_dir, ignore_errors=True)  # an older history must not pass for today's, whatever happens next
    symbols = read_symbols(symbols_csv)
    written, short = 0, []
    with Session(engine or connect()) as session:  # one connection for the whole job (NullPool: one per checkout)
        for symbol in symbols:
            rows = get_history(session, symbol)
            if len(rows) < SESSIONS:
                short.append(f"{symbol}={len(rows)}")
            if rows:
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / f"{symbol}.json").write_text(
                    json.dumps([row.model_dump(mode="json") for row in rows]), encoding="utf-8"
                )
                written += 1
    log.info("wrote the history of %d of %d symbols to %s", written, len(symbols), output_dir)
    if short:
        log.warning("fewer than %d rows: %s", SESSIONS, ", ".join(short))
    if not written:
        log.error("no row found for the %s symbols, nothing written", symbols_csv)
        return NO_DATA
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:3])))
