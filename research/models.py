"""Phase 3 step 3: L2 logistic regression and LightGBM on the 21 inputs, both labels, on the walk-forward of
`research/walk_forward.py`. The settings are fixed in docs/plans/phase-3-logistic-regression-score.md, step 3.

Usage: uv run --group research python -m research.models [features_csv] [output_md]
       uv run --group research python -m research.models --check [features_csv]
Default: out/features.csv and out/models.md. The hold-out is not touched. macOS: LightGBM needs `brew install libomp`.

`--check` runs both models on `beat_median` with the labels shuffled within each session (AUC must be about 0.5) and
with `excess_return_5` plus noise planted in place of one input (AUC must be high): it never reports a real result.
"""

import sys
from collections.abc import Callable
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

from libs.logger import LogxideLogger
from research.baselines import BASELINES, INPUTS
from research.baselines import markdown as baseline_markdown
from research.walk_forward import auc, evaluate, load, split, walk_forward, zscore

C_GRID = (0.001, 0.01, 0.1, 1.0, 10.0)
INNER_MONTHS = 3  # the last 3 calendar months of each training window are its inner test months
LGB_PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 7,
    "min_data_in_leaf": 300,
    "bagging_fraction": 0.7,
    "bagging_freq": 1,
    "feature_fraction": 0.7,
    "seed": 0,
    "deterministic": True,
    "num_threads": 4,
    "verbosity": -1,
}
MAX_ROUNDS, PATIENCE = 500, 50
LABELS = ("beat_median", "hit_3pct_5")
MAIN_METRIC = {"beat_median": "ic", "hit_3pct_5": "lift"}
Fold = dict[str, object]
log = LogxideLogger("models")


def inner_folds(train: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    """Inner walk-forward on the training window only, with the same HORIZON gap as the outer one."""
    months = train["date"].dt.to_period("M").unique()[-INNER_MONTHS:]
    return [split(train, m.start_time, (m + 1).start_time) for m in months]


def logistic(label: str, folds: list[Fold]) -> Callable[[pd.DataFrame, pd.DataFrame], pd.Series]:
    def fit(c: float, rows: pd.DataFrame) -> LogisticRegression:
        return LogisticRegression(C=c, max_iter=1000).fit(zscore(rows, INPUTS), rows[label])

    def predict(model: LogisticRegression, rows: pd.DataFrame) -> pd.Series:
        return pd.Series(model.predict_proba(zscore(rows, INPUTS))[:, 1], index=rows.index)

    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
        train = train[train[label].notna()]
        inner = inner_folds(train)
        loss = {
            c: np.mean([log_loss(te[label], predict(fit(c, tr), te), labels=[0, 1]) for tr, te in inner])
            for c in C_GRID
        }
        c = min(loss, key=loss.get)
        model = fit(c, train)
        folds.append(
            {
                "C": c,
                "train_auc": auc(predict(model, train), train[label]),
                **dict(zip(INPUTS, model.coef_[0], strict=True)),
            }
        )
        return predict(model, test)

    return fit_predict


def lightgbm(label: str, folds: list[Fold]) -> Callable[[pd.DataFrame, pd.DataFrame], pd.Series]:
    """Rounds = the mean best round of the inner folds' early stopping; isotonic map fitted on their predictions.
    `pred` is the raw probability (rank metrics); the calibrated one is kept in `folds` for the Brier skill."""

    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
        train = train[train[label].notna()]
        rounds, inner_pred, inner_label = [], [], []
        for tr, te in inner_folds(train):
            fitted = lgb.Dataset(tr[INPUTS], tr[label])
            booster = lgb.train(
                LGB_PARAMS,
                fitted,
                MAX_ROUNDS,
                valid_sets=[lgb.Dataset(te[INPUTS], te[label], reference=fitted)],
                callbacks=[lgb.early_stopping(PATIENCE, verbose=False)],
            )
            rounds.append(booster.best_iteration)
            inner_pred.append(booster.predict(te[INPUTS], num_iteration=booster.best_iteration))
            inner_label.append(te[label].to_numpy())
        n = max(1, round(float(np.mean(rounds))))
        booster = lgb.train(LGB_PARAMS, lgb.Dataset(train[INPUTS], train[label]), n)
        iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
        iso.fit(np.concatenate(inner_pred), np.concatenate(inner_label))
        raw = booster.predict(test[INPUTS])
        gain = booster.feature_importance("gain")
        folds.append(
            {
                "rounds": n,
                "train_auc": auc(pd.Series(booster.predict(train[INPUTS]), index=train.index), train[label]),
                "calibrated": iso.predict(raw),
                **dict(zip(INPUTS, gain / gain.sum(), strict=True)),
            }
        )
        return pd.Series(raw, index=test.index)

    return fit_predict


MODELS = {"logistic": logistic, "lightgbm": lightgbm}


def run(df: pd.DataFrame, model: str, label: str) -> tuple[pd.DataFrame, list[Fold]]:
    folds: list[Fold] = []
    predicted = walk_forward(df, MODELS[model](label, folds))
    return predicted, folds


def calibration(predicted: pd.DataFrame, label: str) -> pd.DataFrame:
    """Deciles of predicted probability on the whole universe's test rows: mean prediction vs observed share."""
    rows = predicted[predicted[label].notna()]
    bins = pd.qcut(rows["pred"], 10, labels=False, duplicates="drop")
    return rows.groupby(bins).agg(pred=("pred", "mean"), observed=(label, "mean"), rows=(label, "size"))


def table(frame: pd.DataFrame, digits: int = 4) -> list[str]:
    lines = ["| " + " | ".join([frame.index.name or "", *map(str, frame.columns)]) + " |"]
    lines.append("|---" * (len(frame.columns) + 1) + "|")
    for key, row in frame.iterrows():
        lines.append(
            f"| {key} | " + " | ".join(f"{v:.{digits}f}" if isinstance(v, float) else str(v) for v in row) + " |"
        )
    return lines


def main(features_csv: Path = Path("out/features.csv"), output_md: Path = Path("out/models.md")) -> None:
    df = load(features_csv)
    baselines = {name: evaluate(walk_forward(df, fp)) for name, fp in BASELINES.items()}
    out: list[str] = []
    for label in LABELS:
        metric, probability = MAIN_METRIC[label], label == "hit_3pct_5"
        reports, extra = {}, {}
        for model in MODELS:
            predicted, folds = run(df, model, label)
            reports[f"{model}[{label}]"] = evaluate(predicted, probability=probability)
            extra[model] = (predicted, folds)
            log.info(f"{model} on {label} done")
        out += [f"## Trained on `{label}`", "", baseline_markdown(reports)]
        for population in ("universe", "candidates"):
            monthly = pd.DataFrame(
                {
                    **{f"{b}": baselines[b][population]["monthly"][metric] for b in baselines},
                    **{m: r[population]["monthly"][metric] for m, r in reports.items()},
                }
            )
            best_baseline = monthly[list(baselines)].max(axis=1)
            beats = {m: f"{int((monthly[m] > best_baseline).sum())} of {len(monthly)}" for m in reports}
            out += [f"Months above both baselines on {metric}, {population}: {beats}", ""]
            if probability:
                skill = {m: reports[m][population]["brier_skill"] for m in reports}
                months = {m: int((reports[m][population]["monthly"]["brier_skill"] > 0).sum()) for m in reports}
                lgb_predicted, lgb_folds = extra["lightgbm"]
                calibrated = lgb_predicted.assign(pred=np.concatenate([f["calibrated"] for f in lgb_folds]))
                iso = evaluate(calibrated, probability=True)[population]
                skill["lightgbm, isotonic"] = iso["brier_skill"]
                months["lightgbm, isotonic"] = int((iso["monthly"]["brier_skill"] > 0).sum())
                out += [f"Brier skill, {population}: {skill}; months above 0: {months}", ""]
        for model, (predicted, folds) in extra.items():
            fold_frame = pd.DataFrame(folds, index=sorted(predicted["month"].unique())).drop(
                columns="calibrated", errors="ignore"
            )
            test_auc = predicted.groupby("month").apply(lambda g, label=label: auc(g["pred"], g[label]))
            fold_frame.index.name = "month"
            summary = fold_frame.drop(columns=INPUTS).assign(test_auc=test_auc)
            out += [f"### {model} on `{label}`: per fold", "", *table(summary), ""]
            weights = fold_frame[INPUTS].T
            if model == "logistic":
                sign = np.sign(weights)
                majority = np.sign(sign.sum(axis=1)).replace(0, 1)
                weights = pd.DataFrame(
                    {
                        "mean": weights.mean(axis=1),
                        "positive_folds": (sign > 0).sum(axis=1),
                        "minority_folds": (sign.ne(majority, axis=0)).sum(axis=1),
                    }
                )
            else:
                weights = pd.DataFrame(
                    {
                        "mean_gain_share": weights.mean(axis=1),
                        "rank": weights.mean(axis=1).rank(ascending=False).astype(int),
                    }
                )
            weights.index.name = "input"
            out += [*table(weights), ""]
            out += ["Calibration (universe, deciles of raw `pred`):", "", *table(calibration(predicted, label)), ""]
            if model == "lightgbm":
                cal = predicted.assign(pred=np.concatenate([f["calibrated"] for f in folds]))
                out += ["Calibration after isotonic:", "", *table(calibration(cal, label)), ""]
    output_md.write_text("\n".join(out) + "\n", encoding="utf-8")
    log.info(f"models written to {output_md}")


def check(features_csv: Path = Path("out/features.csv")) -> None:
    df = load(features_csv)
    rng = np.random.default_rng(0)
    shuffled = df.copy()
    labels = ["fwd_return_5", "excess_return_5", "beat_median", "hit_3pct_5"]
    shuffled[labels] = df.groupby("date")[labels].transform(lambda s: s.sample(frac=1, random_state=rng).to_numpy())
    planted = df.assign(rsi14=df["excess_return_5"] + rng.normal(0, df["excess_return_5"].std(), len(df)))
    for model in MODELS:
        noise = evaluate(run(shuffled, model, "beat_median")[0])["universe"]
        assert noise["rows"] == 20_447, noise["rows"]
        assert abs(noise["auc_beat_median"] - 0.5) < 0.02, (model, noise["auc_beat_median"])
        signal = evaluate(run(planted, model, "beat_median")[0])["universe"]["auc_beat_median"]
        assert signal > 0.7, (model, signal)
        log.info(f"{model}: shuffled AUC {noise['auc_beat_median']:.3f}, planted AUC {signal:.3f}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--check"]:
        check(*map(Path, sys.argv[2:]))
    else:
        main(*map(Path, sys.argv[1:]))
