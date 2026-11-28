"""Phase 3 step 2: the two baselines (the bar to beat) on the walk-forward of `research/walk_forward.py`.

Usage: uv run --group research python -m research.baselines [features_csv] [output_md]
Default: out/features.csv (from research/export_features.py) and out/baselines.md. The hold-out is not touched.

Baseline 1 is the 0-100 `score`. Baseline 2 is the equal-weight mean of the 21 inputs, each standardised per session
and oriented the way `libs/analysis/scoring.py` rewards it (no learning). Both are ranks, not probabilities, so they
get the rank metrics only (no Brier skill).
"""

import sys
from pathlib import Path

import pandas as pd

from libs.decision import panel
from libs.logger import LogxideLogger
from research.walk_forward import evaluate, load, walk_forward, zscore

# -1: scoring.py gives more points to a lower value (#11 `ramp(6, 1)`, #20 `rank="low"`). `close_vs_sma20` feeds
# #1 (higher is better) and #19 (lower is better); it counts once here, as #1.
LOWER_IS_BETTER = {"sessions_since_cross", "return_volatility"}
INPUTS = list(panel.INPUTS.values())
log = LogxideLogger("baselines")


def score(_train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
    return test["score"]


def equal_weight(_train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
    z = zscore(test, INPUTS)
    z[list(LOWER_IS_BETTER)] *= -1
    return z.mean(axis=1)


BASELINES = {"score": score, "equal_weight": equal_weight}
SUMMARY = ["rows", "sessions", "skipped_sessions", "base_rate_hit", "auc_beat_median", "auc_hit"]
SUMMARY += [f"{metric}_{stat}" for metric in ("ic", "top_bottom", "lift") for stat in ("mean", "t")]


def markdown(reports: dict[str, dict[str, dict]]) -> str:
    columns = [(baseline, population) for baseline, report in reports.items() for population in report]
    lines = ["| metric | " + " | ".join(f"{b} / {p}" for b, p in columns) + " |", "|---" * (len(columns) + 1) + "|"]
    for key in SUMMARY:
        values = [reports[b][p][key] for b, p in columns]
        lines.append(f"| {key} | " + " | ".join(f"{v:,}" if isinstance(v, int) else f"{v:.3f}" for v in values) + " |")
    for metric in ("ic", "lift"):
        monthly = pd.DataFrame({f"{b} / {p}": reports[b][p]["monthly"][metric] for b, p in columns})
        lines += ["", f"Monthly mean {metric}:", "", "| month | " + " | ".join(monthly.columns) + " |"]
        lines.append("|---" * (len(monthly.columns) + 1) + "|")
        lines += [f"| {m} | " + " | ".join(f"{v:.4f}" for v in row) + " |" for m, row in monthly.iterrows()]
    return "\n".join(lines) + "\n"


def main(features_csv: Path = Path("out/features.csv"), output_md: Path = Path("out/baselines.md")) -> None:
    df = load(features_csv)
    reports = {name: evaluate(walk_forward(df, fit_predict)) for name, fit_predict in BASELINES.items()}
    output_md.write_text(markdown(reports), encoding="utf-8")
    log.info(f"baselines written to {output_md}")


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
