"""Phase 3 step 2: the walk-forward evaluation shared by the baselines (step 2), the models (steps 3 and 4) and the
TabICL backtest (Phase 2 step 5). The rules are in docs/plans/phase-3-logistic-regression-score.md, "Decisions".

Monthly test folds, an expanding training window, a gap of HORIZON sessions before each test month, and the hold-out
(from HOLDOUT_START) never used: `walk_forward` stops before it. The one look per label is step 4's (`split` with
HOLDOUT_START), not written yet. Every metric is reported on two populations: the whole universe and the
candidates (score >= MIN_SCORE).
"""

import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from libs.decision.candidates import MIN_SCORE
from libs.decision.outcome import HORIZON

HOLDOUT_START = pd.Timestamp("2026-09-01")
FIRST_TRAIN_MONTHS = 6  # the first test month is the first whole month at least this long after the panel starts
MIN_ROWS = 5  # a per-session metric skips a session with fewer rows (a thin session of candidates)
POPULATIONS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "universe": lambda df: pd.Series(True, index=df.index),
    "candidates": lambda df: df["score"] >= MIN_SCORE,
}
# (train, test) -> one prediction per test row, higher = more likely; a probability when the model gives one
FitPredict = Callable[[pd.DataFrame, pd.DataFrame], pd.Series]


def load(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"])


def zscore(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Standardise each column within its session; missing (or a constant column) becomes 0 after standardising."""
    grouped = df.groupby("date")[columns]
    z = (df[columns] - grouped.transform("mean")) / grouped.transform("std")
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def split(df: pd.DataFrame, test_start: pd.Timestamp, test_end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Training rows end HORIZON sessions before `test_start`, so no training label needs a bar of the test period
    (the panel's dates skip sessions the screen rejected, which only makes the gap longer)."""
    before = np.sort(df.loc[df["date"] < test_start, "date"].unique())
    train = df[df["date"] < before[-HORIZON]] if len(before) > HORIZON else df.iloc[0:0]
    test = df[(df["date"] >= test_start) & (df["date"] < test_end)]
    return train, test


def _predict(train: pd.DataFrame, test: pd.DataFrame, fit_predict: FitPredict) -> pd.DataFrame:
    out = test.assign(pred=fit_predict(train, test))
    for name, population in POPULATIONS.items():
        out[f"base_rate_{name}"] = train.loc[population(train), "hit_3pct_5"].mean()
    return out


def walk_forward(df: pd.DataFrame, fit_predict: FitPredict) -> pd.DataFrame:
    """The test rows of every monthly fold before the hold-out, with `pred`, `month` and the training window's base
    rate of `hit_3pct_5` per population (the bar of the Brier skill)."""
    first = (df["date"].min() + pd.DateOffset(months=FIRST_TRAIN_MONTHS) - pd.Timedelta(days=1)).to_period("M") + 1
    months = pd.period_range(first, (HOLDOUT_START - pd.Timedelta(days=1)).to_period("M"), freq="M")
    folds = [_predict(*split(df, m.start_time, (m + 1).start_time), fit_predict).assign(month=str(m)) for m in months]
    return pd.concat(folds, ignore_index=True)


def auc(pred: pd.Series, label: pd.Series) -> float:
    """Mann-Whitney AUC; ties count one half."""
    known = label.notna() & pred.notna()
    ranks, positive = pred[known].rank(), label[known] == 1
    n1, n0 = positive.sum(), (~positive).sum()
    return float((ranks[positive].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def nonoverlap_t(per_session: pd.Series) -> float:
    """t-stat of the mean on every HORIZON-th session, averaged over the HORIZON offsets (labels overlap otherwise)."""
    values = per_session.dropna().sort_index()
    stats = []
    for offset in range(HORIZON):
        x = values.iloc[offset::HORIZON]
        stats.append(x.mean() / (x.std() / np.sqrt(len(x))))
    return float(np.mean(stats))


def _session(rows: pd.DataFrame) -> pd.Series:
    rows = rows[rows["pred"].notna()]
    k = max(1, round(len(rows) / 5))
    top, bottom = rows.nlargest(k, "pred"), rows.nsmallest(k, "pred")
    hits = rows["hit_3pct_5"].dropna()
    known = rows[rows["fwd_return_5"].notna()]
    return pd.Series(
        {
            "ic": known["pred"].rank().corr(known["fwd_return_5"].rank()),  # Spearman, without scipy
            "top_bottom": top["fwd_return_5"].mean() - bottom["fwd_return_5"].mean(),
            "lift": top["hit_3pct_5"].mean() - hits.mean() if len(hits) else np.nan,
        }
    )


def evaluate(predicted: pd.DataFrame, probability: bool = False) -> dict[str, dict]:
    """Every metric of Phase 3 step 2 on both populations. `probability`: `pred` is P(hit_3pct_5 = 1), so the Brier
    skill against the training window's base rate is computed too."""
    report = {}
    for name, population in POPULATIONS.items():
        rows = predicted[population(predicted) & predicted["pred"].notna()]
        sizes = rows.groupby("date").size()
        kept = rows[rows["date"].isin(sizes[sizes >= MIN_ROWS].index)]
        sessions = kept.groupby("date").apply(_session)
        months = kept[["date", "month"]].drop_duplicates().set_index("date")["month"]
        monthly = sessions.groupby(months).mean()
        result = {
            "rows": len(rows),
            "sessions": len(sessions),
            "skipped_sessions": int((sizes < MIN_ROWS).sum()),
            "base_rate_hit": rows["hit_3pct_5"].mean(),
            "auc_beat_median": auc(rows["pred"], rows["beat_median"]),
            "auc_hit": auc(rows["pred"], rows["hit_3pct_5"]),
            **{f"{metric}_mean": sessions[metric].mean() for metric in sessions},
            **{f"{metric}_t": nonoverlap_t(sessions[metric]) for metric in sessions},
            "monthly": monthly,
        }
        if probability:
            known = rows[rows["hit_3pct_5"].notna()]
            base = known[f"base_rate_{name}"]
            model_error = (known["pred"] - known["hit_3pct_5"]) ** 2
            base_error = (base - known["hit_3pct_5"]) ** 2
            result["brier_skill"] = 1 - model_error.sum() / base_error.sum()
            month = known["month"]
            result["monthly"]["brier_skill"] = 1 - model_error.groupby(month).sum() / base_error.groupby(month).sum()
        report[name] = result
    return report


def self_check(df: pd.DataFrame) -> None:
    """`uv run --group research python -m research.walk_forward [out/features.csv]`: the helper on known answers."""
    dates = np.sort(df["date"].unique())
    for month in pd.period_range("2025-11", "2026-08", freq="M"):
        train, test = split(df, month.start_time, (month + 1).start_time)
        assert ((dates > train["date"].max()) & (dates < test["date"].min())).sum() == HORIZON, month
    oracle = walk_forward(df, lambda _train, test: test["fwd_return_5"])
    assert oracle["date"].max() < HOLDOUT_START
    report = evaluate(oracle)["universe"]
    assert report["ic_mean"] > 0.999 and report["auc_hit"] > 0.999, report
    flat = walk_forward(df, lambda train, test: pd.Series(train["hit_3pct_5"].mean(), index=test.index))
    assert abs(evaluate(flat, probability=True)["universe"]["brier_skill"]) < 1e-9


if __name__ == "__main__":
    self_check(load(Path(sys.argv[1] if len(sys.argv) > 1 else "out/features.csv")))
