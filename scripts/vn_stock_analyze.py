"""Score the shortlisted symbols from their price history (Phase 1, no LLM).

Usage: uv run python -m scripts.vn_stock_analyze [history_dir]
Default: out/vn_stock_history (see vn_stock_get_history). No database, no network: it only reads the JSON files.
The history comes from `prices` and is taken as correct: each file is ascending by date and ends on the session
analysed (the screen already required a bar today), so nothing is re-checked here.
Exit 0 = analysed, 4 = no history file (nothing to analyse), anything else = crash.
"""

import sys
from pathlib import Path

from libs.constants import NO_DATA
from libs.db.models import Price
from libs.logger import Logger, LogxideLogger
from scripts.vn_stock_daily_price_store import read_prices

logger = LogxideLogger("vn_stock_analyze")

History = dict[str, list[Price]]


def load_history(history_dir: Path) -> History:
    """One `<SYMBOL>.json` per symbol (what vn_stock_get_history wrote)."""
    return {path.stem: read_prices(path) for path in sorted(history_dir.glob("*.json"))}


def main(history_dir: Path = Path("out/vn_stock_history"), log: Logger = logger) -> int:
    history = load_history(history_dir)
    if not history:
        log.error("no history in %s, nothing to analyse", history_dir)
        return NO_DATA
    as_of = max(rows[-1].date for rows in history.values())
    log.info("%s: %d symbols to score", as_of, len(history))
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
