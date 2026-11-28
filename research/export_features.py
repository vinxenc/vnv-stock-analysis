"""Phase 3 step 1: write the feature panel to a CSV, print its sanity statistics, run the look-ahead check.

Usage: DATABASE_URL=... uv run python -m research.export_features [output_csv]
Default: out/features.csv. The panel starts on the 70th stored session from BACKFILL_START (the longest lookback of the
21 inputs) and ends on the newest one; the last 5 sessions have no labels. Exit 1 when the look-ahead check finds a
difference or has no stored ranking to compare with (it then proves nothing): run it against a database whose
`vn_stock_rankings` is filled. The sessions of EXPLAINED are left out of the check. Exit 1 too when fewer than WARM_UP
sessions are stored.
"""

import csv
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from libs.db import connect
from libs.decision import panel
from libs.decision.candidates import MIN_SCORE
from libs.indicators import TalibIndicators
from libs.logger import LogxideLogger
from scripts.vn_holiday import off_reason

WARM_UP = 70  # sessions: the most rows any of the 21 inputs needs (#9, #11, #24)
# The backfill of every symbol starts here. Older bars are only the whole histories `vn_stock_dividend_history`
# re-stores from 2019 for a symbol going ex-rights (3 symbols on 2026-11-28): a session of those few is no universe.
BACKFILL_START = dt.date(2025, 1, 2)
COLUMNS = ["date", "symbol", "turnover", *panel.INPUTS.values(), *panel.EXTRA, "score", *panel.LABELS]
# Sessions whose differences are explained by a stored bar that changed after the live run (Phase 3 step 1, production
# run of 2026-11-27): DNSE serves the eve of an ex-date already adjusted after midnight and the sync re-stores it.
# ponytail: one entry per such eve until the price pipeline stops re-storing them; then this list is only history.
EXPLAINED = {
    dt.date(2026, 11, 25): "BVH 2026-11-25 re-stored 56.9 -> 56.09 at 01:12 VN",
    dt.date(2026, 11, 26): "FPT 2026-11-26 re-stored 44.5 -> 43.5 at 00:54 VN",
}
log = LogxideLogger("export_features")


def share(rows: list[dict], label: str) -> str:
    known = [row[label] for row in rows if row[label] is not None]
    return f"{mean(known):.3f} of {len(known)}" if known else "none"


def main(output_csv: Path = Path("out/features.csv")) -> int:
    engine = connect()
    prices = panel.load_prices(engine)  # read once, for the panel and the check
    sessions = sorted({row.date for rows in prices.values() for row in rows if row.date >= BACKFILL_START})
    if len(sessions) < WARM_UP:
        log.error(f"fewer than {WARM_UP} stored sessions: no panel")
        return 1
    start, end = sessions[WARM_UP - 1], sessions[-1]
    indicators = TalibIndicators()
    rows = panel.build_panel(prices, start, end, lambda day: off_reason(day) is None, indicators)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    by_session = defaultdict(list)
    for row in rows:
        by_session[row["date"]].append(row)

    def is_candidate(row: dict) -> bool:
        return row["score"] is not None and row["score"] >= MIN_SCORE

    candidates = [row for row in rows if is_candidate(row)]
    per_session = [sum(map(is_candidate, session)) for session in by_session.values()]
    log.info(f"{output_csv}: {len(rows)} rows, {len(by_session)} sessions ({start} to {end})")
    # a panel of 70 to 74 sessions has no label yet, one without a liquid symbol no session: log, keep the check
    log.info(
        f"hit_3pct_5 share: whole universe {share(rows, 'hit_3pct_5')}, candidates {share(candidates, 'hit_3pct_5')}"
    )
    counts = f"median {median(per_session)}, min {min(per_session)}" if per_session else "no session"
    log.info(f"candidates (score >= {MIN_SCORE}) per session: {counts}, sessions with none {per_session.count(0)}")

    compared, mismatches = panel.lookahead_check(engine, indicators, prices, EXPLAINED)
    log.info(f"look-ahead check: {compared} sessions of vn_stock_rankings compared, {len(mismatches)} differences")
    log.info(f"left out, explained: {', '.join(f'{day} ({why})' for day, why in EXPLAINED.items())}")
    for line in mismatches[:50]:
        log.info("  " + line)
    return 0 if compared and not mismatches else 1


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
