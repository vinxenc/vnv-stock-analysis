# Phase 3 — Logistic regression on the screening indicators

Status: **draft, not started** (2026-11-14). Research first (`research/`), pipeline only if it wins. Related: [phase-1-sql-screens.md](phase-1-sql-screens.md) ("Scoring design", whose weights and thresholds are placeholders), [phase-4-foundation-model-forecasts.md](phase-4-foundation-model-forecasts.md) (why the zero-shot forecasters were set aside), [phase-5-rd-agent.md](phase-5-rd-agent.md).

## Goal

Learn from the data which of the 24 indicators of `libs/analysis` actually tell a stock that will beat its peers over the next 5 sessions from one that will not, instead of the hand-set weights of `libs/analysis/scoring.py`. Output: a probability P(beat the median over 5 sessions) per symbol and session, used to **rank and screen**, never as a buy/sell order (same rule as Phase 2: no recommendations).

Two possible outcomes, both useful:
- The model beats the 0–100 score out of sample → it can be added to the pipeline (step 5).
- It does not → its coefficients still say which indicators to drop, re-weight or flip in `scoring.py`.

## Decisions (2026-11-14)

- **One pooled model for all symbols**, not one per symbol: about 380 rows per symbol (about 75 independent 5-session periods) for 20–32 coefficients would overfit, the cross-sectional label only exists across symbols, and the per-symbol probabilities would not be comparable. Differences between symbols come in as features (size, volatility, later sector), see step 6.
- **Train on many sessions pooled, retrain monthly, score daily.** Not trained per day: one session has about 90 rows, and its labels are only known 5 sessions later.
- Label: 1 when the symbol's 5-session forward return beats the cross-sectional **median** of that session, else 0 (balanced classes, market direction removed).
- Model: L2 logistic regression (scikit-learn); statsmodels only to read the coefficients (its p-values are too optimistic here: rows of one session are correlated and the 5-session labels overlap).
- Inputs are the indicators' **raw values**, not their points, standardised per session (z-score), missing = 0 after standardising. Binary indicators stay 0/1.
- Option B for the history: drop #5 (SMA200) and #17 (250-session high), so the panel starts about 70 sessions into the history instead of about 250 (about 380 sessions instead of about 200). #1 and #19 share one raw value (`close_vs_sma20`), so 20 input columns.

Open:
- The name of the optional dependency group for `research/` (none exists in the repo yet; `research` is the obvious one).

## Step 0. Setup

- [ ] `uv add --group research pandas scikit-learn statsmodels` (not in the main dependencies: CI and the pipeline never install it).
- [ ] Local Postgres per `CLAUDE.md`, `alembic upgrade head` (the price table is `vn_stock_prices` since migration `0007`).

## Step 1. Feature panel (`research/export_features.py` → `out/features.csv`)

Replays `libs/analysis` on every past session: for session t, only the bars up to t of each symbol (`scoring.raw_values(candles, engine)`, as `libs/analysis/report.py` calls it).

- [ ] Universe per session = the screen's rule (20-session average `close × volume` ≥ 20 billion VND, a bar on t).
- [ ] One row per (`date`, `symbol`). Columns:

  | Group | Columns |
  |---|---|
  | id | `date`, `symbol`, `turnover` |
  | inputs (raw, up to t) | `close_vs_sma20`, `close_vs_sma50`, `sma20_above_sma50`, `sma50_change`, `return_20`, `return_60`, `rsi14`, `ppo_histogram`, `ppo_histogram_change`, `sessions_since_cross`, `volume_vs_average`, `up_down_volume_ratio`, `turnover_ratio`, `close_location`, `close_vs_prior_high`, `higher_lows`, `return_volatility`, `no_distribution_day`, `rsi_divergence`, `candle_pattern`, `trendline_breakout` |
  | baseline | `score` (the 0–100 score of that session) |
  | labels (future, never an input) | `fwd_return_5`, `excess_return_5` (minus the session median), `beat_median` (0/1) |

- [ ] #22 and #23 carry their raw strength even when the uptrend gate blocks their points, so the model can learn whether the gate matters.
- [ ] Empty cell = cannot be computed. Labels empty for the last 5 sessions (not used for training).
- [ ] Raw values in the file, no z-score (the same file serves logistic, linear or anything else).
- [ ] **Look-ahead check:** for every session that has rows in `vn_stock_rankings`, the exported raw values equal the stored ones (`indicators[*].raw`; a gated #22 / #23 stores only `sma50_change`, so skip those). Any difference is a bug to fix before going on.
- [ ] Sanity: the share of `beat_median = 1` is about 50% every session; row count about 34,000.

Done when the CSV exists, the look-ahead check passes and the README lists the script.

## Step 2. Baselines (the bar to beat)

- [ ] Walk-forward evaluation helper shared with step 3: monthly folds, expanding training window, **5-session gap** between training and test, metrics on the test months only.
- [ ] Metrics: AUC; rank IC per session (Spearman of prediction vs `fwd_return_5`) with its t-stat computed on **non-overlapping sessions** (every 5th session, averaged over the 5 offsets; the overlapping t-stat inflated TiRex-2's result, see the foundation-model plan); top-fifth minus bottom-fifth return; hit rate.
- [ ] Baseline 1: the current `score`.
- [ ] Baseline 2: equal-weight mean of the standardised inputs (no learning).
- [ ] Write the numbers into this file ("Results").

## Step 3. Logistic regression, 20 inputs

- [ ] L2 logistic, `C` chosen by an inner walk-forward on the training window only (never on the test months).
- [ ] Same metrics as step 2, plus calibration (bins of predicted probability vs observed share) and the coefficients of every fold (sign stability per indicator).
- [ ] Expectations to judge against: AUC 0.52–0.55 is good for stocks; ≥ 0.60 means a leak, look for it before celebrating.
- [ ] If the coefficients are unstable: group the inputs into the 6 themes (6 features) and rerun.
- [ ] Results and the coefficient table go into this file.

**Go / no-go** for step 5, all three on the test months: AUC ≥ 0.52; non-overlapping IC t-stat ≥ 2; beats both baselines on IC in most months.

## Step 4. Extra inputs from `vn_stock_prices`

Only stationary, comparable-across-symbols features; never raw prices or raw volume; nothing after t.

- [ ] `return_1`, `return_5` (short-term reversal)
- [ ] `log_turnover` (size), `amihud` (20-session mean of |daily return| / turnover)
- [ ] `limit_up_days`, `limit_down_days` (sessions at the ±7% HOSE band in 20), `dist_to_ceiling`
- [ ] `gap` (open vs previous close), `range_pct`, `upper_shadow`, `lower_shadow`
- [ ] `max_return_20` (lottery effect), `drawdown_60`
- [ ] `volume_change_1`
- [ ] Skip days whose one-day change is beyond ±7% (ex-rights on adjusted prices) when counting limit days.
- [ ] Rerun step 3 with 20 + these inputs; keep a new input only if the **test** AUC and IC improve.

## Step 5. Use the result (only after a "go")

Pick one:
- [ ] **(a) Re-weight `scoring.py`** from the coefficients (drop, re-weight or flip indicators). No new pipeline; the existing tests and the 95% coverage gate apply.
- [ ] **(b) Add the model to the pipeline:**
  - [ ] Coefficients and standardisation parameters stored in a new table `vn_stock_<thing>` (naming rule in `CLAUDE.md`), one row per training run with its training window and test metrics; Alembic migration.
  - [ ] Monthly retrain: a job of `VN Stock Analysis` that runs on the first session of the month (or when no coefficients exist), not a new workflow; reads `vn_stock_prices`, needs `DATABASE_URL`; ends with `pipeline-state`, added to `notification`'s `needs`.
  - [ ] Daily: `vn_stock_analyze` multiplies today's raw values by the latest coefficients; the probability is stored next to the score in `vn_stock_rankings` and shown in the job summary.
  - [ ] scikit-learn only where needed (the daily part is a dot product and needs none).
  - [ ] Tests with the 95% gate; README updated.
- [ ] Forward check: the first 3 months of live probabilities are evaluated with the same metrics before anyone relies on them.

## Step 6. Later, only if step 3 works

- [ ] Sector (0/1 per sector) and size interactions as inputs.
- [ ] Per-sector models (for example banks, about 15 symbols) when the coefficients differ clearly by sector.
- [ ] Mixed effects (one shared set of coefficients plus shrunk per-symbol deviations).

## Results

(Empty. Fill in per phase: date, sessions, rows, metrics, coefficients.)
