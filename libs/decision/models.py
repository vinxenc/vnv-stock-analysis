from enum import StrEnum


class Decider(StrEnum):
    """The kind of model that answered. The `decider` column of `vn_stock_decisions` accepts exactly these values (a
    CHECK constraint): a new kind is a new migration, see `CLAUDE.md`. Which model of that kind answered is the free
    text `model_name` ("anthropic/claude-opus-5-5", "typesafe/jev", "tabicl/v2"), so a new model needs no migration."""

    LLM = "llm"  # a language model reached by API, the only kind that gives a `reason`
    DECISION_MODEL = "decision_model"  # Jev (TypeSafe): a decision model reached by API, one typed question
    TABULAR = "tabular"  # a model on the symbol's feature row: TabICL, later Phase 3's logistic regression / LightGBM


class Verdict(StrEnum):
    """The answer. The `decision` column of `vn_stock_decisions` accepts exactly these values (a CHECK constraint)."""

    BUY = "buy"
    SKIP = "skip"
