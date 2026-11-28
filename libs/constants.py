from datetime import timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))  # Vietnam has no daylight saving time

# Script exit codes. Not 1: Python exits 1 on an uncaught error, which must not read as "no data".
# Any non-zero code fails the job, except NOT_DUE, which vn-stock-analysis.yml maps to an output.
NO_DATA = 4  # nothing to write or store, or too few symbols (MIN_COVERAGE): a partial outage is not a good run
NOT_DUE = 5  # not an error: the next session to screen is after today, so there is nothing to do yet
MIN_COVERAGE = 0.9  # share of the symbols a run must fetch (or that must have a bar today) to count as complete

# The screen and the history (scripts/vn_stock_screen.py, vn_stock_get_history.py), shared with the feature panel of
# Phase 3 (libs/decision/panel.py), which replays them on past sessions. Rows, not calendar days (holidays).
MIN_TURNOVER = 20_000_000  # thousand VND (prices are in thousand VND) = 20 billion VND per session
TURNOVER_SESSIONS = 20  # the screen's average; a symbol with fewer rows is averaged over the rows it has
HISTORY_SESSIONS = 260  # rows each symbol is scored on: the scoring table's longest lookback is 250 (#17) + a buffer
