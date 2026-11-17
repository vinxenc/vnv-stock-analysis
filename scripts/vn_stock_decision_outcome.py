"""Fill the outcome of every decision whose fifth market session is stored (Phase 2, step 6).

Usage: uv run python -m scripts.vn_stock_decision_outcome
Needs $DATABASE_URL. One UPDATE of `vn_stock_decisions` (`libs/decision/outcome.py`): rows not due yet stay empty
and are picked up by a later run. A due row is left empty while the symbol misses a bar between `t` and `t+5` or a
working day of the holiday calendar (`scripts/vn_holiday.py`) has no stored session, until that bar is stored; and for
good when the symbol moves beyond the price band. Idempotent. The job summary and the log show counts only (the
repository is public).
Exit 0 = done, anything else = crash.
"""

import sys

from sqlalchemy import Engine
from sqlalchemy.exc import StatementError

from libs.db import connect
from libs.decision.outcome import fill_outcomes
from libs.logger import Logger, LogxideLogger, job_summary
from scripts.vn_holiday import off_reason

logger = LogxideLogger("vn_stock_decision_outcome")


def main(engine: Engine | None = None, log: Logger = logger) -> int:
    """Fill the outcomes that are known. Returns the exit code."""
    try:
        with (engine or connect()).begin() as connection:
            filled, left_empty = fill_outcomes(connection, lambda day: off_reason(day) is None)
    except StatementError as error:  # the driver's message may quote a failing row, decision included: keep the cause
        state = getattr(error.orig, "sqlstate", None) or ""
        raise RuntimeError(f"can not fill the outcomes: {type(error.orig).__name__} {state}".rstrip()) from None
    line = (
        f"Decision outcomes: {filled} filled, {left_empty} due but left empty"
        " (missing bar or session, or a move beyond the band)"
    )
    job_summary(line + "\n")
    log.info("%s", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
