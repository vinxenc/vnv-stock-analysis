"""Phase 3 step 1: write the feature panel to a CSV, print its sanity statistics, run the look-ahead check.

Usage: DATABASE_URL=... uv run python -m research.export_features [output_csv]
Default: out/features.csv. The panel starts on the 70th stored session (the longest lookback of the 21 inputs) and ends
on the newest one; the last 5 sessions have no labels. Exit 1 when the look-ahead check finds a difference or has no
stored ranking to compare with (it then proves nothing): run it against a database whose `vn_stock_rankings` is filled.
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from sqlalchemy import text

from libs.db import connect
from libs.decision import panel
from libs.decision.candidates import MIN_SCORE
from libs.indicators import TalibIndicators
from libs.logger import LogxideLogger
from scripts.vn_holiday import off_reason

WARM_UP = 70  # sessions: the most rows any of the 21 inputs needs (#9, #11, #24)
COLUMNS = ["date", "symbol", "turnover", *panel.INPUTS.values(), "score", *panel.LABELS]
log = LogxideLogger("export_features")


def share(rows: list[dict], label: str) -> str:
    known = [row[label] for row in rows if row[label] is not None]
    return f"{mean(known):.3f} of {len(known)}" if known else "none"


def main(output_csv: Path = Path("out/features.csv")) -> int:
    engine = connect()
    with engine.connect() as connection:
        start, end = connection.execute(
            text(
                "SELECT date, (SELECT max(date) FROM vn_stock_prices) FROM (SELECT DISTINCT date FROM vn_stock_prices)"
                " AS d ORDER BY date OFFSET :skip LIMIT 1"
            ),
            {"skip": WARM_UP - 1},
        ).one()
    indicators = TalibIndicators()
    rows = panel.build_panel(engine, start, end, lambda day: off_reason(day) is None, indicators)
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
    beat = [
        mean(r["beat_median"] for r in s if r["beat_median"] is not None)
        for s in by_session.values()
        if any(r["beat_median"] is not None for r in s)
    ]
    log.info(f"{output_csv}: {len(rows)} rows, {len(by_session)} sessions ({start} to {end})")
    log.info(f"beat_median share per session: min {min(beat):.3f}, max {max(beat):.3f}")
    log.info(
        f"hit_3pct_5 share: whole universe {share(rows, 'hit_3pct_5')}, candidates {share(candidates, 'hit_3pct_5')}"
    )
    log.info(
        f"candidates (score >= {MIN_SCORE}) per session: median {median(per_session)}, min {min(per_session)},"
        f" sessions with none {sum(n == 0 for n in per_session)}"
    )

    compared, mismatches = panel.lookahead_check(engine, indicators)
    log.info(f"look-ahead check: {compared} sessions of vn_stock_rankings compared, {len(mismatches)} differences")
    for line in mismatches[:50]:
        log.info("  " + line)
    return 0 if compared and not mismatches else 1


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
