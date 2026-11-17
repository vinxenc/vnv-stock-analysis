"""The outcome of a decision, defined once (docs/plans/phase-2-llm-decision.md, step 6; Phase 3 reuses it).

`t+HORIZON` is the HORIZON-th market session after `t`: the HORIZON-th distinct date after `t` in `vn_stock_prices`, all
symbols. `hit` is set for every decision, buy or skip: true when `close(t+HORIZON) >= close(t) * (1 + TARGET)`, i.e. the
price reached the target, not "the decision was right".
"""

import datetime as dt
from collections.abc import Callable

from sqlalchemy import Connection, text

HORIZON = 5
TARGET = 0.03
MAX_MOVE = 0.075  # beyond HOSE's ±7% band (with a margin to keep a ceiling close): an ex-rights date, adjusted prices

_RANGE = text(
    "SELECT (SELECT min(date) FROM vn_stock_decisions WHERE hit IS NULL), (SELECT max(date) FROM vn_stock_prices)"
)

# A row is filled only when the symbol has a bar on t and on each of the HORIZON sessions after it, none of them moving
# beyond MAX_MOVE from the bar before: counting those bars in (t, t+HORIZON] checks both at once. The working days of
# the holiday calendar in (t, t+HORIZON] must number HORIZON too: a session the sync missed for every symbol is absent
# from the stored dates, which would stretch the window to six sessions. The return is computed in numeric, so an exact
# +3% is a hit and `return_5` and `hit` cannot disagree.
_FILL = text("""
WITH pending AS (
    SELECT date, symbol, model_name FROM vn_stock_decisions WHERE hit IS NULL
),
sessions AS (
    SELECT date, row_number() OVER (ORDER BY date) AS n
    FROM (SELECT DISTINCT date FROM vn_stock_prices WHERE date >= (SELECT min(date) FROM pending)) AS dates
),
due AS (
    SELECT pending.*, s_end.date AS t_end
    FROM pending
    JOIN sessions s_start ON s_start.date = pending.date
    JOIN sessions s_end ON s_end.n = s_start.n + :horizon
    WHERE s_end.date <= CAST(:last AS date)  -- a session stored after _RANGE is beyond the calendar: a later run's
),
bars AS (
    SELECT symbol, date, close, close / lag(close) OVER (PARTITION BY symbol ORDER BY date) - 1 AS change
    FROM vn_stock_prices WHERE date >= (SELECT min(date) FROM pending)
),
outcome AS (
    SELECT due.date, due.symbol, due.model_name, finish.close::numeric / start.close::numeric - 1 AS return_5
    FROM due
    JOIN bars start ON start.symbol = due.symbol AND start.date = due.date
    JOIN bars finish ON finish.symbol = due.symbol AND finish.date = due.t_end
    WHERE (
        SELECT count(*) FROM bars
        WHERE bars.symbol = due.symbol AND bars.date > due.date AND bars.date <= due.t_end
          AND abs(bars.change) <= :max_move
    ) = :horizon
    AND (
        SELECT count(*) FROM unnest(CAST(:working_days AS date[])) AS working(day)
        WHERE working.day > due.date AND working.day <= due.t_end
    ) = :horizon
),
filled AS (
    UPDATE vn_stock_decisions AS d
    SET return_5 = outcome.return_5::float8, hit = outcome.return_5 >= CAST(:target AS numeric)
    FROM outcome
    WHERE (d.date, d.symbol, d.model_name) = (outcome.date, outcome.symbol, outcome.model_name)
    RETURNING 1
)
SELECT (SELECT count(*) FROM filled) AS filled, (SELECT count(*) FROM due) AS due
""")


def fill_outcomes(connection: Connection, is_working_day: Callable[[dt.date], bool]) -> tuple[int, int]:
    """Fill `return_5` and `hit` of every decision whose outcome is known. Returns (filled, due but left empty).

    `is_working_day` is the holiday calendar (the script passes `scripts.vn_holiday`'s); it only guards against a
    missing session: t+HORIZON itself is counted in the stored dates.
    """
    first, last = connection.execute(_RANGE).one()
    days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)] if first and last else []
    params = {
        "horizon": HORIZON,
        "max_move": MAX_MOVE,
        "target": TARGET,
        "working_days": [day for day in days if is_working_day(day)],
        "last": last,
    }
    filled, due = connection.execute(_FILL, params).one()
    return filled, due - filled
