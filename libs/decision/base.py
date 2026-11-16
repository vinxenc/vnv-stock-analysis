"""What every decider gives, as an interface (like `PriceSource` for the price sources).

A decider answers buy or skip, with the probability of buy, for the candidates of one session. The script that stores
the answers (`scripts/vn_stock_llm_decision.py`) only knows `BaseDecider`. To add a decider, subclass it in this
package; a new `kind` also needs a migration (`CLAUDE.md`), a new model of a known kind does not.

Not named `Decider`: that is the enum of the kinds (`libs/decision/models.py`).
"""

import datetime as dt
from abc import ABC, abstractmethod

from libs.analysis.models import Model
from libs.decision.candidates import Candidate
from libs.decision.models import Decider, Verdict


class Decision(Model):
    """One decider's answer about one symbol, as stored in `vn_stock_decisions`."""

    decision: Verdict
    probability: float  # of buy, 0 to 1 (the table has the CHECK)
    reason: str | None = None  # only a decider that explains itself (an LLM)
    input: dict  # what the decider judged from, exact enough to re-read the answer later


class BaseDecider(ABC):
    kind: Decider  # the `decider` column
    model_name: str  # the `model_name` column, "provider/model"

    @abstractmethod
    def decide_all(self, session: dt.date, candidates: list[Candidate]) -> dict[str, Decision]:
        """One decision per candidate of `session`, keyed by symbol (all at once: a tabular model scores the whole
        list in one pass, an API decider loops inside)."""
