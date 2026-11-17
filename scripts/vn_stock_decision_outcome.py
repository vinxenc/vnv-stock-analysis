"""Fill the outcome of every decision whose fifth market session is stored (Phase 2, step 6).

Usage: uv run python -m scripts.vn_stock_decision_outcome
Needs $DATABASE_URL. One UPDATE of `vn_stock_decisions` (`libs/decision/outcome.py`): rows not due yet stay empty
and are picked up by a later run; a due row is left empty for good when the symbol misses a bar or moves beyond the
price band between `t` and `t+5`. Idempotent. The job summary and the log show counts only (the repository is public).
Exit 0 = done, anything else = crash.
"""

import sys

from sqlalchemy import Engine
from sqlalchemy.exc import StatementError

from libs.db import connect
from libs.decision.outcome import fill_outcomes
from libs.logger import Logger, LogxideLogger, job_summary

logger = LogxideLogger("vn_stock_decision_outcome")


def main(engine: Engine | None = None, log: Logger = logger) -> int:
    """Fill the outcomes that are known. Returns the exit code."""
    try:
        with (engine or connect()).begin() as connection:
            filled, left_empty = fill_outcomes(connection)
    except StatementError as error:  # the driver's message may quote a failing row, decision included: keep the cause
        state = getattr(error.orig, "sqlstate", None) or ""
        raise RuntimeError(f"can not fill the outcomes: {type(error.orig).__name__} {state}".rstrip()) from None
    line = f"Decision outcomes: {filled} filled, {left_empty} due but left empty (missing bar or move beyond the band)"
    job_summary(line + "\n")
    log.info("%s", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
