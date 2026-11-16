"""Ask the LLM decider buy or skip for each candidate of the day and store the answers (Phase 2, happy case first).

Usage: uv run python -m scripts.vn_stock_llm_decision [input_json]
Default: out/vn_stock_decision_input.json (what `vn_stock_decision_filter` wrote). Needs $DATABASE_URL,
$OPENROUTER_API_KEY and $LLM_MODEL (the model id as the provider names it, `anthropic/claude-opus-5.5`): the decider is
`LlmDecider` on the `OpenRouter` provider (`libs/decision/llm.py`, `libs/llm/`); the script itself only knows the
`BaseDecider` interface. One API call per candidate, then one upsert into `vn_stock_decisions`, keyed on (date, symbol,
model_name): a rerun overwrites the symbols it answers again, with a new `created_at` and an empty outcome; a symbol it
does not answer keeps its older row.
No candidate: nothing is called or stored. The decisions go to the database only: the job summary and the log show
counts and token totals (the repository is public).
Not built yet (docs/plans/phase-2-llm-decision.md, "Decisions"): the newest-session guard, so a late run decides an
older session, and the handling of one failed symbol, so any failure crashes the run and nothing is stored.
Exit 0 = stored (or no candidate), anything else = crash.
"""

import os
import sys
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.exc import StatementError

from libs.db import connect, upsert
from libs.db.models import DecisionRecord
from libs.decision.base import BaseDecider
from libs.decision.candidates import read_input
from libs.decision.llm import LlmDecider
from libs.decision.models import Verdict
from libs.llm import OpenRouter
from libs.logger import Logger, LogxideLogger, job_summary

logger = LogxideLogger("vn_stock_llm_decision")


def main(
    input_json: Path = Path("out/vn_stock_decision_input.json"),
    engine: Engine | None = None,
    decider: BaseDecider | None = None,
    log: Logger = logger,
) -> int:
    """Decide every candidate of the input, then store the answers. Returns the exit code."""
    data = read_input(input_json)
    if decider is None:  # the default reads the environment, also on a day without a candidate
        model = os.environ.get("LLM_MODEL")  # an unset GitHub variable arrives as an empty string
        if not model:
            raise RuntimeError("$LLM_MODEL is not set: the model id as the provider names it")
        decider = LlmDecider(OpenRouter(), model)
    decisions = decider.decide_all(data.session, data.symbols) if data.symbols else {}
    rows = [
        {
            "date": data.session,
            "symbol": symbol,
            "model_name": decider.model_name,
            "decider": decider.kind,
            **decision.model_dump(mode="json"),  # json: whatever a decider put in `input` can be stored as JSONB
        }
        for symbol, decision in decisions.items()
    ]
    if rows:  # after every call: a failed call leaves the stored rows as they were
        try:
            with (engine or connect()).begin() as connection:
                upsert(connection, DecisionRecord, rows)
        except StatementError as error:
            # SQLAlchemy's message quotes the parameters and the driver's the failing row: neither may reach the
            # public job log, so only the cause's class and SQLSTATE are kept (`from None` drops the original).
            # StatementError, not only DBAPIError: a value that cannot be bound fails before the database sees it.
            state = getattr(error.orig, "sqlstate", None) or ""
            raise RuntimeError(f"can not store the decisions: {type(error.orig).__name__} {state}".rstrip()) from None
    buys = sum(row["decision"] == Verdict.BUY for row in rows)
    line = f"LLM decisions of {data.session}: {len(rows)} symbols decided by {decider.model_name}, {buys} buy"
    job_summary(line + "\n")
    log.info("%s", line)
    return 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
