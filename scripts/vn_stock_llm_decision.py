"""Ask the LLM decider buy or skip for each candidate of the day and store the answers (Phase 2, happy case first).

Usage: uv run python -m scripts.vn_stock_llm_decision [input_json]
Default: out/vn_stock_decision_input.json (what `vn_stock_decision_filter` wrote). Needs $DATABASE_URL and
$OPENROUTER_API_KEY: the decider is `LlmDecider` on the `OpenRouter` provider (`libs/decision/llm.py`, `libs/llm/`);
the script itself only knows the `BaseDecider` interface. One API call per candidate, then one transaction: this
model's rows of the session are deleted and the answers inserted into `vn_stock_decisions`, so a rerun replaces them.
No candidate: nothing is called or stored. The decisions go to the database only: the job summary and the log show
counts and token totals (the repository is public).
Not built yet (docs/plans/phase-2-llm-decision.md, "Decisions"): the newest-session guard, so a late run decides an
older session, and the handling of one failed symbol, so any failure crashes the run and nothing is stored.
Exit 0 = stored (or no candidate), anything else = crash.
"""

import os
import sys
from pathlib import Path

from sqlalchemy import Engine, delete, insert
from sqlalchemy.exc import DBAPIError

from libs.db import connect
from libs.db.models import DecisionRecord
from libs.decision.base import BaseDecider
from libs.decision.candidates import read_input
from libs.decision.llm import LlmDecider
from libs.decision.models import Verdict
from libs.llm import OpenRouter
from libs.logger import Logger, LogxideLogger

logger = LogxideLogger("vn_stock_llm_decision")


def main(
    input_json: Path = Path("out/vn_stock_decision_input.json"),
    engine: Engine | None = None,
    decider: BaseDecider | None = None,
    log: Logger = logger,
) -> int:
    """Decide every candidate of the input, then store the answers. Returns the exit code."""
    data = read_input(input_json)
    decider = decider or LlmDecider(OpenRouter())  # reads $OPENROUTER_API_KEY, also on a day without a candidate
    decisions = decider.decide_all(data.session, data.symbols) if data.symbols else {}
    rows = [
        {
            "date": data.session,
            "symbol": symbol,
            "model_name": decider.model_name,
            "decider": decider.kind,
            **decision.model_dump(),
        }
        for symbol, decision in decisions.items()
    ]
    if rows:  # after every call: a failed call leaves the stored rows as they were
        try:
            with (engine or connect()).begin() as connection:
                connection.execute(
                    delete(DecisionRecord).where(
                        DecisionRecord.date == data.session, DecisionRecord.model_name == decider.model_name
                    )
                )
                connection.execute(insert(DecisionRecord), rows)
        except DBAPIError as error:
            # the driver's message quotes the failing row and SQLAlchemy's the parameters: neither may reach the
            # public job log, so only the error class and the SQLSTATE are kept (`from None` drops the original)
            state = getattr(error.orig, "sqlstate", None)
            raise RuntimeError(f"can not store the decisions: {type(error.orig).__name__} {state}") from None
    buys = sum(row["decision"] == Verdict.BUY for row in rows)
    line = f"LLM decisions of {data.session}: {len(rows)} symbols decided by {decider.model_name}, {buys} buy"
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as file:
            file.write(line + "\n")
    log.info("%s", line)
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
