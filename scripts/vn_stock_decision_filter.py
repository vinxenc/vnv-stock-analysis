"""Pick the day's candidates for the deciders (Phase 2). No database, no network.

Usage: uv run python -m scripts.vn_stock_decision_filter <session> [analysis_json] [history_dir] [output_json]
Default: out/vn_stock_analysis.json + out/vn_stock_history (the artifacts of `vn_stock_analyze` and
`vn_stock_get_history`) -> out/vn_stock_decision_input.json. <session> (YYYY-MM-DD) is the day `vn_stock_analyze`
reports it analysed; it must be the report's `as_of`, so a stale or mixed-up artifact never passes for today's. The
output holds the symbols scored `MIN_SCORE` or more with their last bars (see `libs/decision/candidates.py`); it is an
empty list when nobody reaches it. The job summary shows counts only. Exit 0 = written, 6 = <session> is not the
report's `as_of`, anything else (1 included: a missing history file, a bad date) = crash.
"""

import datetime as dt
import os
import sys
from pathlib import Path

from libs.analysis.models import AnalysisReport
from libs.constants import SESSION_MISMATCH
from libs.decision.candidates import MIN_SCORE, build_input, write_input
from libs.logger import Logger, LogxideLogger

logger = LogxideLogger("vn_stock_decision_filter")


def main(
    session: str,
    analysis_json: Path = Path("out/vn_stock_analysis.json"),
    history_dir: Path = Path("out/vn_stock_history"),
    output_json: Path = Path("out/vn_stock_decision_input.json"),
    log: Logger = logger,
) -> int:
    """Filter the report of `session` into the decision input. Returns the exit code."""
    output_json.unlink(missing_ok=True)  # an older input must not pass for today's, whatever happens next
    report = AnalysisReport.model_validate_json(analysis_json.read_text(encoding="utf-8"))
    if report.as_of != dt.date.fromisoformat(session):
        log.error("the analysis is of %s, not of the session %s: wrong artifact", report.as_of, session)
        return SESSION_MISMATCH
    data = build_input(report, history_dir)
    write_input(data, output_json)
    scored = sum(result.score is not None for result in report.symbols)
    line = f"Decision input of {report.as_of}: {len(data.symbols)} of {scored} scored symbols at {MIN_SCORE} or more"
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as file:
            file.write(line + "\n")
    log.info("%s, written to %s", line, output_json)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], *map(Path, sys.argv[2:5])))
