"""Score the shortlisted symbols from their price history (Phase 1, no LLM).

Usage: uv run python -m scripts.vn_stock_analyze [history_dir] [output_json]
Default: out/vn_stock_history (see vn_stock_get_history) -> out/vn_stock_analysis.json, and the symbols with a score
above 0 upserted into `vn_stock_rankings` (needs $DATABASE_URL). No network: it reads the history files and
data/hose_symbols.csv (the listing dates). The history comes from `vn_stock_prices` and is taken as correct: each file
is ascending by date and ends on the session analysed (the screen already required a bar on it), so nothing is
re-checked here. A rerun of a session overwrites the row of every symbol it scores again; a symbol that left the
shortlist keeps its older row. The ranked table goes to $GITHUB_STEP_SUMMARY when it is set, else to the log.
Exit 0 = analysed and stored, 4 = no history file (nothing to analyse), anything else = crash.
"""

import csv
import datetime as dt
import os
import sys
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from libs.analysis import scoring, summary
from libs.analysis.models import AnalysisReport
from libs.analysis.report import History, build_report
from libs.constants import NO_DATA
from libs.db import connect
from libs.db.models import Ranking
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


def store(report: AnalysisReport, engine: Engine) -> None:
    """Upsert one row per symbol with a score above 0, keyed on (date, timeframe, symbol): a rerun overwrites the
    symbols it scores again. Insufficient data (null) and 0 points are not stored; the JSON and summary keep them."""
    meta = scoring.metadata()
    rows = [
        {
            "date": report.as_of,
            "timeframe": report.timeframe,
            "symbol": result.symbol,
            "score": result.score,
            "coverage": result.coverage,
            "turnover": result.turnover,
            "themes": result.themes,
            "flags": result.flags,
            "indicators": [indicator.model_dump(mode="json") for indicator in result.indicators],
            "metadata": meta,
        }
        for result in report.symbols
        if result.score  # None (insufficient data) or 0
    ]
    if not rows:
        return
    statement = insert(Ranking)
    keys = Ranking.__table__.primary_key.columns
    update = {column.key: column for column in statement.excluded if column.key not in keys}
    with engine.begin() as connection:
        connection.execute(statement.on_conflict_do_update(index_elements=keys, set_=update), rows)


def main(
    history_dir: Path = Path("out/vn_stock_history"),
    output_json: Path = Path("out/vn_stock_analysis.json"),
    engine: Engine | None = None,
    log: Logger = logger,
) -> int:
    """Score the history, write the JSON and the job summary, then upsert the scores. Returns the exit code."""
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
    store(report, engine or connect())  # after the summary: a database error must not hide the ranked table
    scored = sum(result.score is not None for result in report.symbols)
    log.info("%s: %d symbols, %d scored, written to %s", report.as_of, len(report.symbols), scored, output_json)
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:3])))
