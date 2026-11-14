from enum import StrEnum


class Decider(StrEnum):
    """Who answered. The `decider` column of `vn_stock_decisions` accepts exactly these values (a CHECK constraint):
    a new one is a new migration, see `CLAUDE.md`."""

    CLAUDE = "claude"
    JEV = "jev"
    TABICL = "tabicl"


class Verdict(StrEnum):
    """The answer. The `decision` column of `vn_stock_decisions` accepts exactly these values (a CHECK constraint)."""

    BUY = "buy"
    SKIP = "skip"
