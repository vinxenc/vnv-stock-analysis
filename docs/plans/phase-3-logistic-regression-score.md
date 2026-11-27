# Phase 3 — Logistic regression and LightGBM on the screening indicators

Status: **in progress** (2026-11-14; LightGBM added the same day). Steps 0 and 1 are done (2026-11-26; the look-ahead check ran on production on 2026-11-27, every difference explained by two bars re-stored after the live run). Next: step 2. Research first (`research/`), pipeline only if it wins. **Open review findings in [review-debt.md](review-debt.md): read them before starting a step.** Related: [phase-1-sql-screens.md](phase-1-sql-screens.md) ("Scoring design", whose weights and thresholds are placeholders), [phase-4-foundation-model-forecasts.md](phase-4-foundation-model-forecasts.md) (why the zero-shot forecasters were set aside), [phase-5-rd-agent.md](phase-5-rd-agent.md).

## Goal

Learn from the data which of the 24 indicators of `libs/analysis` actually tell a stock that will beat its peers over the next 5 sessions from one that will not, instead of the hand-set weights of `libs/analysis/scoring.py`. Two classic models are trained and compared on the same panel and the same walk-forward: **L2 logistic regression** (linear, readable coefficients) and **LightGBM** (gradient-boosted trees: non-linear, interactions, feature importance). Output: a probability per symbol and session, used to **rank and screen**, never as a buy/sell order by itself (the buy / skip call is Phase 2's, which can take this probability as an input).

The feature panel of step 1 is also the context of Phase 2's TabICL decider, so step 1 is shared work.

Possible outcomes, all useful:
- A model beats the 0–100 score out of sample → it can be added to the pipeline (step 5). If both pass and the gap is small, logistic wins (lighter, readable).
- Neither does → the logistic coefficients and LightGBM's importances still say which indicators to drop, re-weight or flip in `scoring.py`; and the indicators probably carry no signal, whatever the model (Phase 2's deciders included).

## Decisions (2026-11-14)

- **One pooled model for all symbols**, not one per symbol: about 380 rows per symbol (about 75 independent 5-session periods) for 21–35 coefficients (21 inputs, plus the 14 of step 4) would overfit, the cross-sectional label only exists across symbols, and the per-symbol probabilities would not be comparable. Differences between symbols come in as features (size, volatility, later sector), see step 6.
- **Train on many sessions pooled, retrain monthly, score daily.** Not trained per day: one session has about 90 rows, and its labels are only known 5 sessions later.
- Label: 1 when the symbol's 5-session forward return beats the cross-sectional **median** of that session, else 0 (balanced classes, market direction removed). Second label, evaluated the same way: `hit_3pct_5` = `close(t+5) ≥ close(t) × 1.03`, Phase 2's definition of a right buy, so the results here compare with Phase 2's deciders.
- Models: L2 logistic regression (scikit-learn; statsmodels only to read the coefficients, its p-values are too optimistic here: rows of one session are correlated and the 5-session labels overlap) and LightGBM (`lightgbm`, binary objective). LightGBM is kept small because the signal is weak and the rows are correlated: shallow trees (`num_leaves` 7–15), a large `min_data_in_leaf` (a few hundred), subsampling of rows and columns, and the number of rounds chosen by early stopping on the inner walk-forward.
- The panel builder lives in `libs/decision/panel.py` (tested, 95% gate), not in `research/`, because Phase 2's TabICL job calls it every day; `research/` only calls it and writes the CSV.
- **Two populations, every metric on both** (review-debt item 2): the whole universe (about 90 liquid symbols per session) and Phase 2's candidates, the rows of each session with `score >= MIN_SCORE` (`libs/decision/candidates.py`, imported, not copied). Phase 2 decides only the candidates, so only the second set of numbers compares with its deciders and with TabICL's backtest. Models are trained on the whole universe (more rows) and only evaluated on both. Chosen here, change if wrong: a per-session metric of the candidates (rank IC, top minus bottom fifth) skips a session with fewer than 5 candidates, and the report says how many sessions it skipped.
- Inputs are the indicators' **raw values**, not their points, standardised per session (z-score), missing = 0 after standardising. Binary indicators stay 0/1.
- Option B for the history: drop #5 (SMA200) and #17 (250-session high), so the panel starts about 70 sessions into the history instead of about 250 (about 380 sessions instead of about 200). That leaves 22 indicators; #1 and #19 share one raw value (`close_vs_sma20`), so 21 input columns (the table of step 1).
- **Dependencies** (review-debt item 10): the research libraries go in a dependency group `research`, installed only on the user's machine (`uv sync --group research`); no CI or pipeline job installs it, so `setup-env` needs no change for it. `libs/decision/panel.py` sits under the 95% gate, and CI's test job installs only `dev`, so it uses the main dependencies only (numpy, ta-lib, sqlmodel; no pandas): it returns plain rows, and pandas, scikit-learn, statsmodels and lightgbm are imported only in `research/`, which is outside the coverage gate (`--cov=libs --cov=scripts`) and never imported by `tests/`. The audit covers the group anyway (step 0).

## Step 0. Setup

- [x] `uv add --group research pandas scikit-learn statsmodels lightgbm` (not in the main dependencies: CI and the pipeline never install it).
- [x] CI's audit (`.github/workflows/ci.yml`, job `audit`) exports `--no-dev` only, so it would never see this group: change its `uv export` to `--all-groups`, so every group is audited, `research` now and `tabicl` (Phase 2 step 5) later, with no change per group (`dev` is audited too, which costs nothing).
- [x] Local Postgres per `CLAUDE.md`, `alembic upgrade head` (the price table is `vn_stock_prices` since migration `0007`).

## Step 1. Feature panel (`libs/decision/panel.py`, `research/export_features.py` → `out/features.csv`)

Replays `libs/analysis` on every past session: for session t, the same window the live run reads, the last `HISTORY_SESSIONS` (260) bars of each symbol up to t, never all bars up to t (`scoring.raw_values(candles, engine)`, as `libs/analysis/report.py` calls it). RSI and PPO are recursive (Wilder's smoothing, EMAs), so their value depends on where the window starts: a longer window would give slightly different inputs from the ones the live run scored and stored (review-debt item 14). The constant moved from `scripts/vn_stock_get_history.py` (`SESSIONS`) to `libs/constants.py` (`HISTORY_SESSIONS`), with the screen's `MIN_TURNOVER` and `TURNOVER_SESSIONS`, so the scripts and `panel.py` import the same ones (`libs/` never imports `scripts/`).

- [x] `libs/decision/panel.py`: `build_panel(engine, start, end, is_working_day, indicators)` → rows as below (the calendar is passed in, as `fill_outcomes` takes it, since `libs/` never imports `scripts/`); unit-tested on hand-made bars (no look-ahead, labels empty when t+5 is not there yet, at most `SESSIONS` bars per replay). Main dependencies only (see "Decisions"). `research/export_features.py` calls it and writes the CSV.

- [x] Universe per session = the screen's rule (20-session average `close × volume` ≥ 20 billion VND, a bar on t).
- [x] One row per (`date`, `symbol`). Columns:

  | Group | Columns |
  |---|---|
  | id | `date`, `symbol`, `turnover` |
  | inputs (raw, up to t) | `close_vs_sma20`, `close_vs_sma50`, `sma20_above_sma50`, `sma50_change`, `return_20`, `return_60`, `rsi14`, `ppo_histogram`, `ppo_histogram_change`, `sessions_since_cross`, `volume_vs_average`, `up_down_volume_ratio`, `turnover_ratio`, `close_location`, `close_vs_prior_high`, `higher_lows`, `return_volatility`, `no_distribution_day`, `rsi_divergence`, `candle_pattern`, `trendline_breakout` |
  | baseline | `score` (the 0–100 score of that session) |
  | labels (future, never an input) | `fwd_return_5`, `excess_return_5` (minus the session median), `beat_median` (0/1), `hit_3pct_5` (0/1, `fwd_return_5 ≥ 0.03`) |

- [x] #22 and #23 carry their raw strength even when the uptrend gate blocks their points, so the model can learn whether the gate matters.
- [x] Empty cell = cannot be computed. Labels empty for the last 5 sessions (not used for training).
- [x] The forward labels use `HORIZON`, `TARGET` and the market calendar of `libs/decision/outcome.py` (Phase 2 step 6: `t+5` is the fifth distinct date after `t` in `vn_stock_prices`), not a definition of their own; a test checks that `hit_3pct_5` equals the stored `hit` of `vn_stock_decisions` on the same rows. Built as a Python function `outcome` next to the SQL `_FILL` in `outcome.py` (the SQL's per-row subqueries do not scale to the panel's rows); `test_panel.py` runs both on every rule of `_FILL` (the five exact +3% pairs, a ceiling close, a 10% gap, a missing bar, a halt on t+5, t+5 not stored, a session missed for every symbol, a holiday).
- [x] Raw values in the file, no z-score (the same file serves logistic, linear or anything else).
- [x] **Look-ahead check:** for every session that has rows in `vn_stock_rankings`, the replayed raw values equal the stored ones (`indicators[*].raw`, every key; a gated #22 / #23 stores only `sma50_change`, which the replay's gated result holds too), within a tolerance (`math.isclose`, `rel_tol=1e-6`, `abs_tol=1e-9`: the windows are the same, so only float noise is allowed). Any difference beyond it is a bug, or a stored bar that changed after the live run (say which), to fix or explain before going on. It covers only the sessions stored since 2026-11-11, not the whole panel. Indicator 12 is stored in two forms, told apart by the `up_day` key of its `raw` (#33):
  - Rows without `up_day` (stored before 2026-11-16) hold the gated value in `volume_vs_average`: 0 on a session that was not an up day. That is the `strength` of the `Detection` that `up_day_volume_ratio` still returns, so compare the strength.
  - Rows with `up_day` hold the real ratio in `volume_vs_average`: compare the ratio, and `up_day` too.

  So the check compares the replay's indicator results (`score_indicators`, what the live run stored), not the CSV, whose `volume_vs_average` is always the real ratio; only an old-form #12 is converted (the gated value: the ratio on an up day, else 0).

  Built (`lookahead_check` in `panel.py`, run by `research/export_features.py`, tested on stored rankings made by the live path); it compares every key of the stored `raw`, `percentile` included, so it also checks that the replayed universe is the live one. The local database has no ranking, so it compared 0 sessions there; the user ran it on production (it only reads): `DATABASE_URL=<production> uv run --group research python -m research.export_features`, exit 0 only when at least one session was compared and nothing differs.

  **Production run (2026-11-27): passes, every difference explained.** 11 sessions compared (2026-11-11 to 2026-11-26), 9 of them identical, the old-form #12 rows included. The 46 differences come from two bars only, re-stored after the live run had scored them:
  - BVH 2026-11-25: the 19:13 VN sync stored close 56.9, the scheduled sync at 01:12 VN the next night stored 56.09 (open, high, low scaled by the same 0.9858, volume unchanged).
  - FPT 2026-11-26: 44.5 at 19:37 VN, then 43.5 at 00:54 VN (1,000 VND less, about 0.9775).
  - Every other difference is a `percentile` of #6 or #20 with an identical raw value: the two changed values moved their neighbours in the ranking.

  Cause, from the `vn-stock-latest-prices` artifacts of both syncs of each day: after midnight DNSE returns the latest bar already adjusted for the next day's ex-date, and the store's upsert overwrites the raw bar the analysis read, while the older bars stay unadjusted. Same night: MSH 2026-11-25 34.6 → 30.6, PDN 2026-11-26 77.5 → 76.5, VPX 2026-11-26 21.15 → 14.59 (not in the rankings). So the panel is right; the stored prices carry a one-session step on the eve of an ex-date, below `MAX_MOVE` for a cash dividend (BVH, FPT, PDN). It skews the inputs and labels around those dates, as the dividend adjustment of Phase 1's Notes does; the fix belongs to the price pipeline, not to this plan. Until it is fixed the check exits 1 on these known bars.
- [x] Sanity: the share of `beat_median = 1` is about 50% every session; row count about 34,000. Record the share of `hit_3pct_5 = 1` on both populations of "Decisions", over the whole panel: a sanity statistic only. The base rate a result is compared with is computed by the step 2 helper on the same population and the same test months as that result, since the share can drift over time. Record the number of candidates per session too (median, minimum, sessions with none).

Chosen while building it (2026-11-26, change if wrong):
- #12's `up_day` is not a column: the CSV keeps 21 inputs (review-debt item 12), so the model sees the real volume ratio without the up-day gate the score applies. Adding `up_day` would make 22.
- `score` lacks #5 and #17 until a symbol has 200 and 250 rows, so early in the panel it is out of at most 92 points and the `score >= 40` population is a little harder to reach there than live. The step 2 helper compares a result with the base rate of the same months, so this only shifts the candidates over time.

Done when the CSV exists, the look-ahead check passes and the README lists the script. Done (2026-11-27).

## Step 2. Baselines (the bar to beat)

- [ ] Walk-forward evaluation helper shared with step 3: monthly folds, expanding training window, **5-session gap** between training and test, metrics on the test months only.
- [ ] Metrics: AUC; rank IC per session (Spearman of prediction vs `fwd_return_5`) with its t-stat computed on **non-overlapping sessions** (every 5th session, averaged over the 5 offsets; the overlapping t-stat inflated TiRex-2's result, see the foundation-model plan); top-fifth minus bottom-fifth return; hit rate, next to the base rate of the same rows (the share of `hit_3pct_5 = 1` or `beat_median = 1` on the test months). The helper reports each metric twice, on the whole universe and on the candidates (`score >= MIN_SCORE`, see "Decisions"), from the same predictions; steps 3 and 4 and Phase 2's TabICL backtest use the same helper, so their numbers come in both forms too.
- [ ] Baseline 1: the current `score`.
- [ ] Baseline 2: equal-weight mean of the standardised inputs (no learning).
- [ ] Write the numbers into this file ("Results").

## Step 3. Logistic regression and LightGBM, 21 inputs

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
- [ ] Rerun step 3 (both models) with 21 + these inputs. Choose which new inputs to keep **inside each training window** (its inner walk-forward), never from the test months: the outer test months then score the whole procedure (selection included) once, and their numbers stay an honest estimate.

## Step 5. Use the result (only after a "go")

Pick one:
- [ ] **(a) Re-weight `scoring.py`** from the coefficients (drop, re-weight or flip indicators). No new pipeline; the existing tests and the 95% coverage gate apply.
- [ ] **(b) Add the model to the pipeline:**
  - [ ] The trained model stored in a new table `vn_stock_<thing>` (naming rule in `CLAUDE.md`), one row per training run with its training window and test metrics; Alembic migration. Logistic: coefficients and standardisation parameters. LightGBM: the booster as text (`model_to_string`) and its calibration map.
  - [ ] Monthly retrain: a job of `VN Stock Analysis` that runs on the first session of the month (or when no coefficients exist), not a new workflow; reads `vn_stock_prices`, needs `DATABASE_URL`; ends with `pipeline-state`, added to `notification`'s `needs`.
  - [ ] Daily: `vn_stock_analyze` multiplies today's raw values by the latest coefficients (logistic), or, for LightGBM, loads the stored booster text, predicts on today's raw values and applies the stored calibration map; the probability is stored next to the score in `vn_stock_rankings` and shown in the job summary.
  - [ ] scikit-learn only where needed (the daily logistic part is a dot product and needs none; LightGBM needs `lightgbm` in the job that scores, in its own dependency group, installed through `setup-env`'s `groups` input of Phase 2 step 5).
  - [ ] Tests with the 95% gate; README updated.
- [ ] **(c) A `tabular` model in Phase 2** (a new `model_name`, no migration), only if the `hit_3pct_5` model passed its own go / no-go: that model's probability of `hit_3pct_5` above a threshold = buy, stored in `vn_stock_decisions` next to Claude, Jev and TabICL and scored the same way.
- [ ] Forward check: the first 3 months of live probabilities are evaluated with the same metrics before anyone relies on them.

## Step 6. Later, only if step 3 works

- [ ] Sector (0/1 per sector) and size interactions as inputs.
- [ ] Per-sector models (for example banks, about 15 symbols) when the coefficients differ clearly by sector.
- [ ] Mixed effects (one shared set of coefficients plus shrunk per-symbol deviations).

## Results

Fill in per phase: date, sessions, rows, metrics, coefficients.

**Step 1, local database (2026-11-26)**, prices from 2025-01-02 to 2026-11-09 (406 symbols): 41,439 rows over 390 sessions (2025-04-17 to 2026-11-09), about 106 symbols per session, more than the about 34,000 rows expected. `beat_median = 1` share per session: 0.458 to 0.500 (below 0.5 when ties or an odd count leave the median row at 0). `hit_3pct_5 = 1` share: 0.242 of 40,962 labelled rows on the whole universe, 0.260 of 13,289 on the candidates (`score >= 40`). Candidates per session: median 28, minimum 6, no session without one. About 50 s on a laptop.

**Step 1, production (2026-11-27)**, prices up to 2026-11-26: 42,524 rows over 402 sessions (2025-04-17 to 2026-11-26). `beat_median = 1` share per session: 0.458 to 0.500. `hit_3pct_5 = 1` share: 0.238 of 42,037 on the whole universe, 0.257 of 13,591 on the candidates. Candidates per session: median 28, minimum 6, none without. Look-ahead check: see step 1.
