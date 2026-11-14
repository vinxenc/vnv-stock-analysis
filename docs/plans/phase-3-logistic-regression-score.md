# Phase 3 — Logistic regression and LightGBM on the screening indicators

Status: **draft, not started** (2026-11-14; LightGBM added the same day). Research first (`research/`), pipeline only if it wins. **Open review findings in [review-debt.md](review-debt.md): read them before starting a step.** Related: [phase-1-sql-screens.md](phase-1-sql-screens.md) ("Scoring design", whose weights and thresholds are placeholders), [phase-4-foundation-model-forecasts.md](phase-4-foundation-model-forecasts.md) (why the zero-shot forecasters were set aside), [phase-5-rd-agent.md](phase-5-rd-agent.md).

## Goal

Learn from the data which of the 24 indicators of `libs/analysis` actually tell a stock that will beat its peers over the next 5 sessions from one that will not, instead of the hand-set weights of `libs/analysis/scoring.py`. Two classic models are trained and compared on the same panel and the same walk-forward: **L2 logistic regression** (linear, readable coefficients) and **LightGBM** (gradient-boosted trees: non-linear, interactions, feature importance). Output: a probability per symbol and session, used to **rank and screen**, never as a buy/sell order by itself (the buy / skip call is Phase 2's, which can take this probability as an input).

The feature panel of step 1 is also the context of Phase 2's TabICL decider, so step 1 is shared work.

Possible outcomes, all useful:
- A model beats the 0–100 score out of sample → it can be added to the pipeline (step 5). If both pass and the gap is small, logistic wins (lighter, readable).
- Neither does → the logistic coefficients and LightGBM's importances still say which indicators to drop, re-weight or flip in `scoring.py`; and the indicators probably carry no signal, whatever the model (Phase 2's deciders included).

## Decisions (2026-11-14)

- **One pooled model for all symbols**, not one per symbol: about 380 rows per symbol (about 75 independent 5-session periods) for 20–32 coefficients would overfit, the cross-sectional label only exists across symbols, and the per-symbol probabilities would not be comparable. Differences between symbols come in as features (size, volatility, later sector), see step 6.
- **Train on many sessions pooled, retrain monthly, score daily.** Not trained per day: one session has about 90 rows, and its labels are only known 5 sessions later.
- Label: 1 when the symbol's 5-session forward return beats the cross-sectional **median** of that session, else 0 (balanced classes, market direction removed). Second label, evaluated the same way: `hit_3pct_5` = `close(t+5) ≥ close(t) × 1.03`, Phase 2's definition of a right buy, so the results here compare with Phase 2's deciders.
- Models: L2 logistic regression (scikit-learn; statsmodels only to read the coefficients, its p-values are too optimistic here: rows of one session are correlated and the 5-session labels overlap) and LightGBM (`lightgbm`, binary objective). LightGBM is kept small because the signal is weak and the rows are correlated: shallow trees (`num_leaves` 7–15), a large `min_data_in_leaf` (a few hundred), subsampling of rows and columns, and the number of rounds chosen by early stopping on the inner walk-forward.
- The panel builder lives in `libs/decision/panel.py` (tested, 95% gate), not in `research/`, because Phase 2's TabICL job calls it every day; `research/` only calls it and writes the CSV.
- Inputs are the indicators' **raw values**, not their points, standardised per session (z-score), missing = 0 after standardising. Binary indicators stay 0/1.
- Option B for the history: drop #5 (SMA200) and #17 (250-session high), so the panel starts about 70 sessions into the history instead of about 250 (about 380 sessions instead of about 200). #1 and #19 share one raw value (`close_vs_sma20`), so 20 input columns.

Open:
- The name of the optional dependency group for `research/` (none exists in the repo yet; `research` is the obvious one).

## Step 0. Setup

- [ ] `uv add --group research pandas scikit-learn statsmodels lightgbm` (not in the main dependencies: CI and the pipeline never install it).
- [ ] Local Postgres per `CLAUDE.md`, `alembic upgrade head` (the price table is `vn_stock_prices` since migration `0007`).

## Step 1. Feature panel (`libs/decision/panel.py`, `research/export_features.py` → `out/features.csv`)

Replays `libs/analysis` on every past session: for session t, only the bars up to t of each symbol (`scoring.raw_values(candles, engine)`, as `libs/analysis/report.py` calls it).

- [ ] `libs/decision/panel.py`: `build_panel(engine, start, end)` → rows as below; unit-tested on hand-made bars (no look-ahead, labels empty when t+5 is not there yet). `research/export_features.py` calls it and writes the CSV.

- [ ] Universe per session = the screen's rule (20-session average `close × volume` ≥ 20 billion VND, a bar on t).
- [ ] One row per (`date`, `symbol`). Columns:

  | Group | Columns |
  |---|---|
  | id | `date`, `symbol`, `turnover` |
  | inputs (raw, up to t) | `close_vs_sma20`, `close_vs_sma50`, `sma20_above_sma50`, `sma50_change`, `return_20`, `return_60`, `rsi14`, `ppo_histogram`, `ppo_histogram_change`, `sessions_since_cross`, `volume_vs_average`, `up_down_volume_ratio`, `turnover_ratio`, `close_location`, `close_vs_prior_high`, `higher_lows`, `return_volatility`, `no_distribution_day`, `rsi_divergence`, `candle_pattern`, `trendline_breakout` |
  | baseline | `score` (the 0–100 score of that session) |
  | labels (future, never an input) | `fwd_return_5`, `excess_return_5` (minus the session median), `beat_median` (0/1), `hit_3pct_5` (0/1, `fwd_return_5 ≥ 0.03`) |

- [ ] #22 and #23 carry their raw strength even when the uptrend gate blocks their points, so the model can learn whether the gate matters.
- [ ] Empty cell = cannot be computed. Labels empty for the last 5 sessions (not used for training).
- [ ] Raw values in the file, no z-score (the same file serves logistic, linear or anything else).
- [ ] **Look-ahead check:** for every session that has rows in `vn_stock_rankings`, the exported raw values equal the stored ones (`indicators[*].raw`; a gated #22 / #23 stores only `sma50_change`, so skip those). Any difference is a bug to fix before going on.
- [ ] Sanity: the share of `beat_median = 1` is about 50% every session; row count about 34,000. Record the share of `hit_3pct_5 = 1` (the base rate Phase 2's buys must beat).

Done when the CSV exists, the look-ahead check passes and the README lists the script.

## Step 2. Baselines (the bar to beat)

- [ ] Walk-forward evaluation helper shared with step 3: monthly folds, expanding training window, **5-session gap** between training and test, metrics on the test months only.
- [ ] Metrics: AUC; rank IC per session (Spearman of prediction vs `fwd_return_5`) with its t-stat computed on **non-overlapping sessions** (every 5th session, averaged over the 5 offsets; the overlapping t-stat inflated TiRex-2's result, see the foundation-model plan); top-fifth minus bottom-fifth return; hit rate.
- [ ] Baseline 1: the current `score`.
- [ ] Baseline 2: equal-weight mean of the standardised inputs (no learning).
- [ ] Write the numbers into this file ("Results").

## Step 3. Logistic regression and LightGBM, 20 inputs

Both models on the same folds, both labels (`beat_median` first, `hit_3pct_5` second).

- [ ] L2 logistic, `C` chosen by an inner walk-forward on the training window only (never on the test months).
- [ ] LightGBM with the small settings of "Decisions"; rounds by early stopping on the same inner walk-forward. Raw inputs (trees need no z-score; missing values stay missing, LightGBM handles them).
- [ ] Same metrics as step 2 for both, plus calibration (bins of predicted probability vs observed share; LightGBM's probabilities are often over-confident, so try isotonic calibration on the inner folds), the logistic coefficients of every fold (sign stability per indicator) and LightGBM's gain importance per fold.
- [ ] Expectations to judge against: AUC 0.52–0.55 is good for stocks; ≥ 0.60 means a leak, look for it before celebrating. LightGBM much better than logistic on training folds but not on test months = overfitting: shrink it further.
- [ ] If the coefficients are unstable: group the inputs into the 6 themes (6 features) and rerun both.
- [ ] Results, the coefficient table and the importance table go into this file.

**Go / no-go** for step 5, **per model and per label** (each label has its own trained models), all three on the test months: AUC ≥ 0.52; non-overlapping IC t-stat ≥ 2; beats both baselines on IC in most months. A pass on `beat_median` says nothing about `hit_3pct_5`: step 5c needs the `hit_3pct_5` model's own pass. If both model types pass for a label, logistic is kept unless LightGBM is clearly better (for example a higher IC in most months).

## Step 4. Extra inputs from `vn_stock_prices`

Only stationary, comparable-across-symbols features; never raw prices or raw volume; nothing after t.

- [ ] `return_1`, `return_5` (short-term reversal)
- [ ] `log_turnover` (size), `amihud` (20-session mean of |daily return| / turnover)
- [ ] `limit_up_days`, `limit_down_days` (sessions at the ±7% HOSE band in 20), `dist_to_ceiling`
- [ ] `gap` (open vs previous close), `range_pct`, `upper_shadow`, `lower_shadow`
- [ ] `max_return_20` (lottery effect), `drawdown_60`
- [ ] `volume_change_1`
- [ ] Skip days whose one-day change is beyond ±7% (ex-rights on adjusted prices) when counting limit days.
- [ ] Rerun step 3 (both models) with 20 + these inputs. Choose which new inputs to keep **inside each training window** (its inner walk-forward), never from the test months: the outer test months then score the whole procedure (selection included) once, and their numbers stay an honest estimate.

## Step 5. Use the result (only after a "go")

Pick one:
- [ ] **(a) Re-weight `scoring.py`** from the coefficients (drop, re-weight or flip indicators). No new pipeline; the existing tests and the 95% coverage gate apply.
- [ ] **(b) Add the model to the pipeline:**
  - [ ] The trained model stored in a new table `vn_stock_<thing>` (naming rule in `CLAUDE.md`), one row per training run with its training window and test metrics; Alembic migration. Logistic: coefficients and standardisation parameters. LightGBM: the booster as text (`model_to_string`) and its calibration map.
  - [ ] Monthly retrain: a job of `VN Stock Analysis` that runs on the first session of the month (or when no coefficients exist), not a new workflow; reads `vn_stock_prices`, needs `DATABASE_URL`; ends with `pipeline-state`, added to `notification`'s `needs`.
  - [ ] Daily: `vn_stock_analyze` multiplies today's raw values by the latest coefficients (logistic), or, for LightGBM, loads the stored booster text, predicts on today's raw values and applies the stored calibration map; the probability is stored next to the score in `vn_stock_rankings` and shown in the job summary.
  - [ ] scikit-learn only where needed (the daily logistic part is a dot product and needs none; LightGBM needs `lightgbm` in the job that scores, in its own dependency group).
  - [ ] Tests with the 95% gate; README updated.
- [ ] **(c) A `tabular` model in Phase 2** (a new `model_name`, no migration), only if the `hit_3pct_5` model passed its own go / no-go: that model's probability of `hit_3pct_5` above a threshold = buy, stored in `vn_stock_decisions` next to Claude, Jev and TabICL and scored the same way.
- [ ] Forward check: the first 3 months of live probabilities are evaluated with the same metrics before anyone relies on them.

## Step 6. Later, only if step 3 works

- [ ] Sector (0/1 per sector) and size interactions as inputs.
- [ ] Per-sector models (for example banks, about 15 symbols) when the coefficients differ clearly by sector.
- [ ] Mixed effects (one shared set of coefficients plus shrunk per-symbol deviations).

## Results

(Empty. Fill in per phase: date, sessions, rows, metrics, coefficients.)
