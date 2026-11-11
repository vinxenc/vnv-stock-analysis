"""Score the shortlisted symbols from their price history (Phase 1, no LLM).

Usage: uv run python -m scripts.vn_stock_analyze [history_dir] [output_json]
Default: out/vn_stock_history (see vn_stock_get_history) -> out/vn_stock_analysis.json. No database, no network: it
only reads the history files and data/hose_symbols.csv (the listing dates). The history comes from `prices` and is taken
as correct: each file is ascending by date and ends on the session analysed (the screen already required a bar
on it), so nothing is re-checked here. The ranked table goes to $GITHUB_STEP_SUMMARY when it is set, else to the log.
Exit 0 = analysed, 4 = no history file (nothing to analyse), anything else = crash.
"""

import csv
import datetime as dt
import os
import sys
from pathlib import Path

from libs.analysis import summary
from libs.analysis.report import History, build_report
from libs.constants import NO_DATA
from libs.indicators import TalibIndicators
from libs.logger import Logger, LogxideLogger
from scripts.vn_stock_daily_price_store import read_prices

SYMBOLS_CSV = Path("data/hose_symbols.csv")
logger = LogxideLogger("vn_stock_analyze")


def load_history(history_dir: Path) -> History:
    """One `<SYMBOL>.json` per symbol (what vn_stock_get_history wrote)."""
    return {path.stem: read_prices(path) for path in sorted(history_dir.glob("*.json"))}


def read_listed_dates(path: Path = SYMBOLS_CSV) -> dict[str, dt.date]:
    with path.open(encoding="utf-8", newline="") as file:
        return {row["code"]: dt.date.fromisoformat(row["listed_date"]) for row in csv.DictReader(file)}


def main(
    history_dir: Path = Path("out/vn_stock_history"),
    output_json: Path = Path("out/vn_stock_analysis.json"),
    log: Logger = logger,
) -> int:
    output_json.unlink(missing_ok=True)  # an older analysis must not pass for today's, whatever happens next
    history = load_history(history_dir)
    if not history:
        log.error("no history in %s, nothing to analyse", history_dir)
        return NO_DATA
    report = build_report(history, read_listed_dates(), TalibIndicators())
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    table = summary.render(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as file:
            file.write(table)
    else:
        log.info("\n%s", table)
    scored = sum(result.score is not None for result in report.symbols)
    log.info("%s: %d symbols, %d scored, written to %s", report.as_of, len(report.symbols), scored, output_json)
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:3])))
