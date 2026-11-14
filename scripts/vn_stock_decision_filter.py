"""Pick the day's candidates for the deciders (Phase 2). No database, no network.

Usage: uv run python -m scripts.vn_stock_decision_filter [analysis_json] [history_dir] [output_json]
Default: out/vn_stock_analysis.json + out/vn_stock_history (the artifacts of `vn_stock_analyze` and
`vn_stock_get_history`, both of the same run) -> out/vn_stock_decision_input.json. The day is the report's `as_of`; it
goes into the output as `session`. The output holds the symbols scored `MIN_SCORE` or more with their last bars (see
`libs/decision/candidates.py`); it is an empty list when nobody reaches it. The job summary shows counts only.
Exit 0 = written, anything else = crash (a missing file, a history file missing for a candidate).
"""

import os
import sys
from pathlib import Path

from libs.analysis.models import AnalysisReport
from libs.decision.candidates import MIN_SCORE, build_input, write_input
from libs.logger import Logger, LogxideLogger

logger = LogxideLogger("vn_stock_decision_filter")


def main(
    analysis_json: Path = Path("out/vn_stock_analysis.json"),
    history_dir: Path = Path("out/vn_stock_history"),
    output_json: Path = Path("out/vn_stock_decision_input.json"),
    log: Logger = logger,
) -> int:
    """Filter the report into the decision input. Returns the exit code."""
    output_json.unlink(missing_ok=True)  # an older input must not pass for today's, whatever happens next
    report = AnalysisReport.model_validate_json(analysis_json.read_text(encoding="utf-8"))
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
    sys.exit(main(*map(Path, sys.argv[1:4])))
