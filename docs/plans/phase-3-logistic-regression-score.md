# Phase 3 — Logistic regression and LightGBM on the screening indicators

Status: **in progress** (2026-11-14; LightGBM added the same day). Steps 0 and 1 are done (2026-11-26; the look-ahead check ran on production on 2026-11-27 and found 46 differences (exit 1), every one explained by two bars re-stored after the live run, none a panel bug). Step 2 is done (2026-11-28, #41): neither baseline has a signal, see "Results". Step 3 is done (2026-11-28): logistic on `beat_median` passes the test-month bars on the candidates only, nothing passes on `hit_3pct_5` for the candidates, and LightGBM replaces neither primary once the rules name their population (settled with the user after step 3, see "Decisions"). Step 4 is built and run on the local database (2026-11-28), with provisional results: on the walk-forward test months neither label's kept configuration passes on both populations (`beat_median`: logistic on 21 inputs, fails the universe; `hit_3pct_5`: logistic on 35 inputs, which replaces the primary, fails the candidates), see "Results". Next: the same run on a production export, which decides; then the user decides whether the hold-out look is still run. Research first (`research/`), pipeline only if it wins. **Open review findings in [review-debt.md](review-debt.md): read them before starting a step.** Related: [phase-1-sql-screens.md](phase-1-sql-screens.md) ("Scoring design", whose weights and thresholds are placeholders), [phase-4-foundation-model-forecasts.md](phase-4-foundation-model-forecasts.md) (why the zero-shot forecasters were set aside), [phase-5-rd-agent.md](phase-5-rd-agent.md).

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
- **How `hit_3pct_5` is judged** (review-debt item 3). This label follows the market: in a good week most symbols reach +3%, in a bad week few do. Pooled AUC therefore mixes sessions, and it is not comparable between the two models: logistic on per-session z-scores cannot see the market level, while LightGBM on raw inputs can learn regimes from about 75 periods. Rank IC is cross-sectional, while Phase 2 uses an absolute target. So `hit_3pct_5` is judged on what Phase 2 step 9 measures, with the session as the unit:
  - **Precision lift:** per session, the hit rate of the top fifth by predicted probability minus that session's base rate (the share of the same population that hit). Report its mean over the test sessions and its t-stat on non-overlapping sessions, the same way as the IC. The top fifth stands in for Phase 2's buy rule, which is still open (Phase 2 step 9). It is cross-sectional, so the absolute level is carried by the Brier skill below.
  - **Brier skill:** `1 − Brier(model) / Brier(base-rate predictor)`, pooled over the test rows, and per test month. The base-rate predictor gives every row the share of `hit_3pct_5 = 1` in its training window, on the same population (the candidates' share for the candidates' numbers, 0.257 against 0.238 on production). The same-session share is not known at `t`, so it is never the bar. A plain sign: above 0, and above 0 in most test months.
  - AUC and rank IC are still reported for `hit_3pct_5`, for reference only.
  - Baselines 1 and 2 (step 2) are ranks, not probabilities. They are measured on the precision lift only, and the Brier bar is the base-rate predictor.
- **One primary configuration, a hold-out used once** (review-debt item 7). Steps 3 and 4 try 2 models × 2 labels × up to 3 input sets on about 10 test months, so one would pass by chance.
  - The primary configuration is L2 logistic, `beat_median`, the 21 base inputs.
  - Step 5c needs a `hit_3pct_5` model, so that label has its own primary: logistic, the 21 base inputs. Chosen here, change if wrong. The reviewer named one configuration; a second one means a second look at the hold-out.
  - Every other run is a secondary configuration: LightGBM, the 6 themes, a smaller LightGBM, the inputs of step 4. Each is listed in "Results" with its numbers, so the count of what was tried is known.
  - A secondary replaces the primary of its label only if it beats it on the walk-forward test months by this rule: a higher non-overlapping t-stat of the label's main metric (IC for `beat_median`, precision lift for `hit_3pct_5`), and better in most months.
  - **Hold-out:** every session from 2026-09-01 on (about the last 3 months of labelled sessions when this was written, 2026-11-28). The date is fixed and does not slide. Steps 2 to 4 never see it. The walk-forward ends with August 2026, and with the 5-session gap at the boundary: a row, training or test, whose `t+5` falls on or after 2026-09-01 is dropped.
  - With a first training window of about 6 months (from 2025-04-17), that leaves about 10 walk-forward test months (2025-11 to 2026-08). Chosen here, change if wrong.
  - **One look per label**, so two at most, after step 4. The look scores the kept configuration of that label, trained on every row before the gap. It runs on the production database, because the local one ends 2026-11-09.
  - A fail on the hold-out is final for that label: no changed configuration is run on it again.
  - The hold-out pass rule is fixed now. The hold-out has about 60 sessions, about 12 non-overlapping, too few for t ≥ 2. So it needs no t-stat: the label's main metric must be above 0 and beat both baselines, plus, for `hit_3pct_5`, a Brier skill above 0.
  - Phase 2's TabICL backtest uses the same helper, so it leaves the hold-out alone too. Whether TabICL gets a look at it, and which bar it must pass, is review-debt item 8.
- **Which population each rule reads** (user, 2026-11-28, **chosen after seeing step 3's results**, which named no population for three rules; the strictest reading, so that the choice cannot favour a result):
  - The go / no-go of both labels, on the test months and on the hold-out, must pass on **both** populations.
  - A secondary replaces the primary of its label only if the replace rule holds on **both** populations.
  - The smaller-LightGBM trigger (overfitting) reads the **whole universe**, the rows the models are trained on.
  - So, after step 3, both primaries stay logistic, and `beat_median` misses the test-month bars on the universe (IC t 1.56).
- Models: L2 logistic regression (scikit-learn; no statsmodels, dropped in step 3: scikit-learn's coefficients are enough, and its p-values would be too optimistic here, rows of one session being correlated and the 5-session labels overlapping) and LightGBM (`lightgbm`, binary objective). LightGBM is kept small because the signal is weak and the rows are correlated: shallow trees (`num_leaves` 7–15), a large `min_data_in_leaf` (a few hundred), subsampling of rows and columns, and the number of rounds chosen by early stopping on the inner walk-forward.
- The panel builder lives in `libs/decision/panel.py` (tested, 95% gate), not in `research/`, because Phase 2's TabICL job calls it every day; `research/` only calls it and writes the CSV.
- **Two populations, every metric on both** (review-debt item 2): the whole universe (about 90 liquid symbols per session) and Phase 2's candidates, the rows of each session with `score >= MIN_SCORE` (`libs/decision/candidates.py`, imported, not copied). Phase 2 decides only the candidates, so only the second set of numbers compares with its deciders and with TabICL's backtest. Models are trained on the whole universe (more rows) and only evaluated on both. Chosen here, change if wrong: a per-session metric of the candidates (rank IC, top minus bottom fifth) skips a session with fewer than 5 candidates, and the report says how many sessions it skipped.
- Inputs are the indicators' **raw values**, not their points, standardised per session (z-score), missing = 0 after standardising. Binary indicators are z-scored too (changed in step 3, 2026-11-28: one rule for every input, as baseline 2).
- Option B for the history: drop #5 (SMA200) and #17 (250-session high), so the panel starts about 70 sessions into the history instead of about 250 (about 380 sessions instead of about 200). That leaves 22 indicators; #1 and #19 share one raw value (`close_vs_sma20`), so 21 input columns (the table of step 1).
- **Dependencies** (review-debt item 10): the research libraries go in a dependency group `research`, installed only on the user's machine (`uv sync --group research`); no CI or pipeline job installs it, so `setup-env` needs no change for it. `libs/decision/panel.py` sits under the 95% gate, and CI's test job installs only `dev`, so it uses the main dependencies only (numpy, ta-lib, sqlmodel; no pandas): it returns plain rows, and pandas, scikit-learn, statsmodels and lightgbm are imported only in `research/`, which is outside the coverage gate (`--cov=libs --cov=scripts`) and never imported by `tests/`. The audit covers the group anyway (step 0). The group is created by the first step that imports one of these libraries (step 2), not before: step 0 added it early, and it was dropped on 2026-11-28 because nothing imported it yet.

## Step 0. Setup

- [x] ~~`uv add --group research pandas scikit-learn statsmodels lightgbm`~~ Dropped (2026-11-28): no code imports them yet; step 2 adds the ones it imports, to the `research` group (not the main dependencies: CI and the pipeline never install it).
- [x] CI's audit (`.github/workflows/ci.yml`, job `audit`) exports `--no-dev` only, so it would never see this group: change its `uv export` to `--all-groups`, so every group is audited, `dev` now and `research` (step 2) and `tabicl` (Phase 2 step 5) once they exist, with no change per group (`dev` is audited too, which costs nothing).
- [x] Local Postgres per `CLAUDE.md`, `alembic upgrade head` (the price table is `vn_stock_prices` since migration `0007`).

## Step 1. Feature panel (`libs/decision/panel.py`, `research/export_features.py` → `out/features.csv`)

Replays `libs/analysis` on every past session: for session t, the same window the live run reads, the last `HISTORY_SESSIONS` (260) bars of each symbol up to t, never all bars up to t (`scoring.raw_values(candles, engine)`, as `libs/analysis/report.py` calls it). RSI and PPO are recursive (Wilder's smoothing, EMAs), so their value depends on where the window starts: a longer window would give slightly different inputs from the ones the live run scored and stored (review-debt item 14). The constant moved from `scripts/vn_stock_get_history.py` (`SESSIONS`) to `libs/constants.py` (`HISTORY_SESSIONS`), with the screen's `MIN_TURNOVER` and `TURNOVER_SESSIONS`, so the scripts and `panel.py` import the same ones (`libs/` never imports `scripts/`).

- [x] `libs/decision/panel.py`: `build_panel(prices, start, end, is_working_day, indicators)` (`prices` from `load_prices(engine)`, read once for the panel and the check) → rows as below (the calendar is passed in, as `fill_outcomes` takes it, since `libs/` never imports `scripts/`); unit-tested on hand-made bars (no look-ahead, labels empty when t+5 is not there yet, at most `SESSIONS` bars per replay). Main dependencies only (see "Decisions"). `research/export_features.py` calls it and writes the CSV.

- [x] Universe per session = the screen's rule (20-session average `close × volume` ≥ 20 billion VND, a bar on t), on the sessions the screen would accept: a working day, and `MIN_COVERAGE` of the previous stored session's symbols with a bar on t (added 2026-11-27; the local panel is unchanged, 41,439 rows; production not re-run). A skipped session still counts in `t+5`, as in `_FILL`.
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

  Built (`lookahead_check` in `panel.py`, run by `research/export_features.py`, tested on stored rankings made by the live path); it compares every key of the stored `raw`, `percentile` included, so it also checks that the replayed universe is the live one. The local database has no ranking, so it compared 0 sessions there; the user ran it on production (it only reads): `DATABASE_URL=<production> uv run python -m research.export_features`, exit 0 only when at least one session was compared and nothing differs.

  **Production run (2026-11-27): 46 differences, exit 1, every one explained; no difference is a panel bug.** 11 sessions compared (2026-11-11 to 2026-11-26), 9 of them identical, the old-form #12 rows included. The 46 differences come from two bars only, re-stored after the live run had scored them:
  - BVH 2026-11-25: the 19:13 VN sync stored close 56.9, the scheduled sync at 01:12 VN the next night stored 56.09 (open, high, low scaled by the same 0.9858, volume unchanged).
  - FPT 2026-11-26: 44.5 at 19:37 VN, then 43.5 at 00:54 VN (1,000 VND less, about 0.9775).
  - Every other difference is a `percentile` of #6 or #20 with an identical raw value: the two changed values moved their neighbours in the ranking.

  Cause, from the `vn-stock-latest-prices` artifacts of both syncs of each day: after midnight DNSE returns the latest bar already adjusted for the next day's ex-date, and the store's upsert overwrites the raw bar the analysis read, while the older bars stay unadjusted. Same night: MSH 2026-11-25 34.6 → 30.6, PDN 2026-11-26 77.5 → 76.5, VPX 2026-11-26 21.15 → 14.59 (not in the rankings). So the panel is right; the stored prices carry a one-session step on the eve of an ex-date, below `MAX_MOVE` for a cash dividend (BVH, FPT, PDN). It skews the inputs and labels around those dates, as the dividend adjustment of Phase 1's Notes does; the fix belongs to the price pipeline, not to this plan. Since 2026-11-27 `research/export_features.py` leaves these two sessions out of the check (`EXPLAINED`), so a difference on any other session exits 1 again. A stopgap: each eve of an ex-date re-stored this way adds a session to that list until the price pipeline stops it. Not re-run on production since.
- [x] Sanity: the share of `beat_median = 1` is about 50% every session (true by construction, so `export_features` stopped logging it on 2026-11-28; the results below keep the recorded range); row count about 34,000. Record the share of `hit_3pct_5 = 1` on both populations of "Decisions", over the whole panel: a sanity statistic only. The base rate a result is compared with is computed by the step 2 helper on the same population and the same test months as that result, since the share can drift over time. Record the number of candidates per session too (median, minimum, sessions with none).

Chosen while building it (2026-11-26, change if wrong):
- #12's `up_day` is not a column: the CSV keeps 21 inputs (review-debt item 12), so the model sees the real volume ratio without the up-day gate the score applies. Adding `up_day` would make 22.
- `score` lacks #5 and #17 until a symbol has 200 and 250 rows, so early in the panel it is out of at most 92 points and the `score >= 40` population is a little harder to reach there than live. The step 2 helper compares a result with the base rate of the same months, so this only shifts the candidates over time.

Done when the CSV exists, the look-ahead check passes and the README lists the script. Done (2026-11-27): the check did not pass as such (46 differences, exit 1), but every difference is explained by a stored bar that changed after the live run, which the step allows.

## Step 2. Baselines (the bar to beat)

- [x] Walk-forward evaluation helper shared with step 3 (`research/walk_forward.py`): monthly folds, expanding training window, **5-session gap** between training and test, metrics on the test months only. It never uses a session of the hold-out (from 2026-09-01, see "Decisions"), neither for training nor for testing, nor through a label (the last 5 sessions before it are dropped). The one look per label is a separate run, made on purpose after step 4.
- [x] Metrics: AUC; rank IC per session (Spearman of prediction vs `fwd_return_5`) with its t-stat computed on **non-overlapping sessions** (every 5th session, averaged over the 5 offsets; the overlapping t-stat inflated TiRex-2's result, see the foundation-model plan); top-fifth minus bottom-fifth return; for `hit_3pct_5`, the precision lift and the Brier skill of "Decisions" (per session, against the same session's base rate and the training window's base rate). The helper reports each metric twice, on the whole universe and on the candidates (`score >= MIN_SCORE`, see "Decisions"), from the same predictions; steps 3 and 4 and Phase 2's TabICL backtest use the same helper, so their numbers come in both forms too.
- [x] Baseline 1: the current `score` (`research/baselines.py`).
- [x] Baseline 2: equal-weight mean of the standardised inputs (no learning). Chosen while building it, change if wrong: every input is z-scored per session, the binary ones too, so each weighs the same. Each is oriented the way `scoring.py` rewards it: `sessions_since_cross` and `return_volatility` reversed; `close_vs_sma20` counts once, as #1, though #19 rewards the opposite.
- [x] Write the numbers into this file ("Results").

## Step 3. Logistic regression and LightGBM, 21 inputs

Both models on the same folds, both labels (`beat_median` first, `hit_3pct_5` second).

Settings fixed before the first real run (2026-11-28, `research/models.py`; changing one after seeing the results is a new secondary configuration, listed in "Results"):
- Inputs: the 21 columns of step 1 only (no `score`, no `turnover`). Training rows whose label is empty are dropped.
- Logistic: every input z-scored per session with the step 2 helper, the binary ones too (as baseline 2; "Decisions" said binary inputs stay 0/1 and now follows this, change if wrong). `C` from {0.001, 0.01, 0.1, 1, 10}, the one with the lowest mean log loss on the inner folds.
- Inner walk-forward: the last 3 calendar months of each training window are its inner test months, each split with the same 5-session gap (`split`).
- LightGBM: learning rate 0.05, `num_leaves` 7, `min_data_in_leaf` 300, `bagging_fraction` 0.7 every round, `feature_fraction` 0.7, seed 0, deterministic, 4 threads; at most 500 rounds, early stopping after 50 on each inner fold (log loss); the final model is fitted on the whole training window with the mean of the inner folds' best rounds. Isotonic calibration fitted on the inner folds' predictions only; the rank metrics use the raw probability, the Brier skill is reported for both.
- Unstable coefficients (the trigger of the 6-theme rerun): an input is unstable when its logistic coefficient has the minority sign in 3 or more of the 10 folds; the rerun happens when 7 or more of the 21 inputs are unstable, for either label.
- Overfitting (the trigger of the smaller LightGBM): LightGBM's mean training AUC exceeds its mean test-month AUC by 0.05 or more more than logistic's gap does, and its test numbers are not better than logistic's. The smaller one: `num_leaves` 3, `min_data_in_leaf` 1000, everything else the same.
- `python -m research.models --check` runs both models on `beat_median` with the labels shuffled within each session (AUC must stay within 0.02 of 0.5) and with `excess_return_5` plus noise in place of `rsi14` (AUC above 0.7). It reports no real result.

- [x] L2 logistic, `C` chosen by an inner walk-forward on the training window only (never on the test months).
- [x] LightGBM with the small settings of "Decisions"; rounds by early stopping on the same inner walk-forward. Raw inputs (trees need no z-score; missing values stay missing, LightGBM handles them).
- [x] Same metrics as step 2 for both, plus calibration (bins of predicted probability vs observed share; LightGBM's probabilities are often over-confident, so try isotonic calibration on the inner folds), the logistic coefficients of every fold (sign stability per indicator) and LightGBM's gain importance per fold.
- [x] Expectations to judge against: AUC 0.52–0.55 is good for stocks; ≥ 0.60 means a leak, look for it before celebrating. LightGBM much better than logistic on training folds but not on test months = overfitting. A smaller LightGBM is then one more secondary configuration (see "Decisions"), listed in "Results".
- [x] If the coefficients are unstable: group the inputs into the 6 themes (6 features) and rerun both, as secondary configurations.
- [x] Results, the coefficient table and the importance table go into this file.

**Go / no-go** for step 5, **per label**, on the kept configuration of that label: its primary, unless a secondary replaced it by the rule of "Decisions". It is judged after step 4, first on the walk-forward test months, then once on the hold-out, each bar on both populations ("Decisions"):
- `beat_median`, on the test months: AUC ≥ 0.52; non-overlapping IC t-stat ≥ 2; beats both baselines on IC in most months.
- `hit_3pct_5`, on the test months (review-debt item 3): non-overlapping precision-lift t-stat ≥ 2; Brier skill above 0, and above 0 in most months; beats both baselines on precision lift in most months. Phase 2 decides only the candidates, so the candidates' numbers matter most for step 5c, but the universe must pass too.
- Then the hold-out, with the pass rule of "Decisions". A fail there is a no-go for that label.

A pass on `beat_median` says nothing about `hit_3pct_5`: step 5c needs the `hit_3pct_5` model's own pass.

## Step 4. Extra inputs from `vn_stock_prices`

Only stationary, comparable-across-symbols features; never raw prices or raw volume; nothing after t.

Definitions, fixed before the first run (2026-11-28, user: "as proposed"). Computed in `libs/decision/panel.py` (`EXTRA`, a tuple of its own: `INPUTS` stays the 21 of step 3, so the baselines and the primaries do not change) on the same window as the 21 inputs, the symbol's last `HISTORY_SESSIONS` bars up to t. `r_d = close_d / close_{d−1} − 1` between two consecutive stored bars of the symbol. A cell is empty when its bars are not there.
- [x] `return_1` = `r_t`; `return_5` = `close_t / close_{t−5} − 1` (short-term reversal).
- [x] `log_turnover` = `ln` of the 20-session mean of `close × volume` (the `turnover` column); `amihud` = `ln` of the 20-session mean of `|r_d| / (close_d × volume_d)`, over the days with a volume (log, because the ratio spans orders of magnitude between symbols).
- [x] `limit_up_days`, `limit_down_days`: sessions of the last 20 at the ceiling or the floor, by the rule of `gates.flags` (`CEILING` 7%, `CEILING_TOLERANCE` 0.5%, since tick rounding leaves a ceiling close just under +7%): `r_d ≥ 1.07 × 0.995 − 1` (about +6.47%), `r_d ≤ 0.93 × 1.005 − 1` (about −6.53%). The universe is HOSE only (`data/hose_symbols.csv`), so one band fits every symbol.
- [x] `dist_to_ceiling` = `close_{t−1} × 1.07 / close_t − 1`, the room left under t's own ceiling. It is a monotone function of `return_1` (`1.07 / (1 + r_t) − 1`), so it adds nothing to LightGBM and is nearly collinear with `return_1` for logistic. Kept as approved; it costs one line.
- [x] `gap` = `open_t / close_{t−1} − 1`; `range_pct` = `(high_t − low_t) / close_t`; `upper_shadow` = `(high_t − max(open_t, close_t)) / close_t`; `lower_shadow` = `(min(open_t, close_t) − low_t) / close_t`.
- [x] `max_return_20` = the largest `r_d` of the last 20 sessions (lottery effect); `drawdown_60` = `close_t / max(close of the last 60 sessions) − 1`.
- [x] `volume_change_1` = `ln(volume_t / volume_{t−1})`, empty when `volume_{t−1}` is 0.
- [x] Days beyond `MAX_MOVE` (7.5%, `libs/decision/outcome.py`): an ex-rights date on adjusted prices, not a move. Since PR #38 `vn_stock_dividend_history` re-stores a symbol's whole history on its ex-rights date, but ex-rights dates before its 2026-11-20 seed stay unrepaired unless re-run (Phase 1, Notes). So `limit_up_days`, `limit_down_days` and `max_return_20` skip those days, and `return_1`, `gap` and `dist_to_ceiling` are empty on a session t whose `|r_t|` is beyond it, as `outcome` leaves a label empty. Count on the local database (2026-11-28, prices to 2026-11-27): 0 to 18 such bars a month from 2025-01 to 2026-08 among about 8,000, except 40 in April 2025.
- [x] Rerun step 3 (both models, the settings of step 3 unchanged: the `C` grid, LightGBM's parameters, the inner walk-forward) with the 21 + 14 = 35 inputs, as secondary configurations (see "Decisions"). **No selection of inputs:** all 35 go in, L2 (which chose its strongest penalty in step 3) and LightGBM's small trees and column subsampling do the shrinking, so there is no selection step to fit on the test months. Each 35-input run is compared with its label's primary (logistic, 21 inputs) by the replace rule, on both populations. The hold-out gives the final estimate.
- [x] Run on a new CSV (`out/features_step4.csv`), never over step 3's (`out/features.csv`, production). Before trusting it, its 21 old inputs, `score` and labels are compared with step 3's CSV on the rows before 2026-09-01; if they differ, the 21-input primary is rerun on the new CSV and the 35-input runs are compared with that, never with step 3's table. "Results" says which.
- [x] `--check` on the 35 inputs first, then one real run. Any change after seeing its numbers is a new secondary configuration, listed in "Results".

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

**Step 2, baselines (2026-11-28)**, on `out/features.csv` of the production run of step 1 (2025-04-17 to 2026-11-26). Walk-forward test months 2025-11 to 2026-08, without the last 5 sessions of August (their label reads a hold-out bar; PR #41 review): 200 sessions, hold-out untouched. `uv run --group research python -m research.baselines`, about 15 s. Base rate of `hit_3pct_5` on these test months: 0.218 on the whole universe, 0.214 on the candidates (below the whole panel's 0.238 and 0.257, so the share drifts, as step 1 expected). No session had fewer than 5 candidates.

| metric | score / universe | score / candidates | equal weight / universe | equal weight / candidates |
|---|---|---|---|---|
| rows | 20,193 | 5,493 | 20,447 | 5,493 |
| AUC `beat_median` | 0.486 | 0.486 | 0.484 | 0.487 |
| AUC `hit_3pct_5` | 0.483 | 0.508 | 0.499 | 0.519 |
| rank IC, mean | −0.032 | −0.070 | −0.025 | −0.051 |
| rank IC, non-overlapping t | −0.84 | −1.97 | −0.67 | −1.32 |
| months with IC > 0 | 5 of 10 | 2 of 10 | 3 of 10 | 3 of 10 |
| top minus bottom fifth, 5-session return | −0.0% | −0.7% | −0.1% | −0.4% |
| precision lift (top fifth), mean | +0.012 | −0.013 | +0.006 | +0.024 |
| precision lift, non-overlapping t | 0.65 | −0.47 | 0.32 | 0.70 |

The universe's `score` column has 254 fewer rows than the equal-weight one: rows without a score (not scored by the gates) are dropped from that baseline.

Monthly mean rank IC (step 3's "beats both baselines in most months" compares with these):

| month | score / universe | score / candidates | equal_weight / universe | equal_weight / candidates |
|---|---|---|---|---|
| 2025-11 | -0.0372 | 0.0489 | -0.0410 | 0.0695 |
| 2025-12 | 0.0973 | -0.0408 | 0.0981 | 0.0612 |
| 2026-01 | 0.0585 | 0.0288 | 0.0652 | -0.0048 |
| 2026-02 | 0.0238 | -0.0425 | -0.0344 | -0.0670 |
| 2026-03 | -0.2312 | -0.2284 | -0.1427 | -0.1840 |
| 2026-04 | -0.0763 | -0.0455 | -0.0385 | 0.0045 |
| 2026-05 | -0.0875 | -0.0379 | -0.0859 | -0.0181 |
| 2026-06 | 0.0044 | -0.1056 | -0.0049 | -0.1461 |
| 2026-07 | 0.0456 | -0.0968 | 0.0343 | -0.0999 |
| 2026-08 | -0.1412 | -0.1804 | -0.1498 | -0.1317 |

Monthly mean precision lift:

| month | score / universe | score / candidates | equal_weight / universe | equal_weight / candidates |
|---|---|---|---|---|
| 2025-11 | 0.0211 | 0.1478 | 0.0234 | 0.2032 |
| 2025-12 | 0.1114 | -0.0198 | 0.0822 | 0.0250 |
| 2026-01 | 0.0570 | 0.0574 | 0.0533 | 0.0464 |
| 2026-02 | 0.0573 | -0.0292 | 0.0470 | -0.0740 |
| 2026-03 | -0.0231 | -0.0337 | -0.0232 | -0.0440 |
| 2026-04 | -0.0086 | 0.0073 | 0.0049 | 0.1101 |
| 2026-05 | 0.0325 | -0.0109 | 0.0258 | 0.0260 |
| 2026-06 | 0.0040 | -0.1076 | -0.0109 | -0.0924 |
| 2026-07 | -0.0667 | -0.0625 | -0.0720 | 0.0027 |
| 2026-08 | -0.0786 | -0.0743 | -0.0737 | 0.0363 |

Reading:
- Neither baseline has a signal on these months. Every t-stat is under 2 in absolute value, and every AUC is between 0.48 and 0.52.
- The `score` leans slightly the wrong way, mostly on the candidates (IC −0.070, t −1.97, 8 of 10 months negative; March 2026 alone −0.23). A higher score has meant a slightly lower 5-session return. This is a hint for step 3 (look for inputs whose sign the score has backwards, and for short-term reversal in step 4), not a result: it misses t = 2.
- So step 3's go / no-go is mostly a bar against "no signal": the two baselines are about zero.
- The helper was checked before these numbers were trusted (2026-11-28). `tests/` never imports `research/`, so every check below but the random one is kept as `uv run --group research python -m research.walk_forward` (asserts, exit 0 when they hold). The same numbers came out of a clean environment built from `uv.lock` alone (`uv run --isolated`):
  - A prediction equal to `fwd_return_5` gives IC 1.0 and AUC `hit_3pct_5` 1.0.
  - A random one gives IC −0.01 (t −0.6) and AUC 0.49 to 0.50.
  - The training base rate used as the model gives a Brier skill of exactly 0 on the universe.
  - Every fold has 5 panel sessions between its last training date and its first test date.
  - The last test session is 5 panel sessions before 2026-09-01, so no label reads a hold-out bar. The hold-out's first session is 2026-09-03.

**Step 3, logistic and LightGBM on the 21 inputs (2026-11-28)**, same CSV, folds and test months as step 2 (2025-11 to 2026-08, 200 sessions, 20,447 rows on the universe, 5,493 on the candidates; hold-out untouched). `uv run --group research python -m research.models`, about 25 s; the full tables (per fold, coefficients, gain importance, calibration) go to `out/models.md`. The settings are the ones fixed in step 3 before this run (commit `921403e`); `--check` passed first (shuffled labels: AUC 0.502 logistic, 0.498 LightGBM; planted signal: 0.776, 0.778). Two runs gave the same numbers. After the code review of the same day, logistic z-scores a training session over all its rows before dropping the unlabelled ones, as the test rows are; the numbers above are from that run (the logistic ones moved in the third decimal, IC t on the candidates 2.34 → 2.30).

| metric | logistic `beat_median` / universe | / candidates | LightGBM `beat_median` / universe | / candidates |
|---|---|---|---|---|
| AUC `beat_median` | 0.516 | 0.529 | 0.520 | 0.547 |
| rank IC, mean | 0.042 | 0.087 | 0.049 | 0.060 |
| rank IC, non-overlapping t | 1.56 | 2.30 | 1.74 | 1.48 |
| months IC above both baselines | 8 of 10 | 8 of 10 | 8 of 10 | 8 of 10 |
| top minus bottom fifth, 5-session return | +0.2% | +1.0% | +0.4% | +0.6% |
| mean train AUC / test AUC (universe) | 0.550 / 0.514 | | 0.590 / 0.521 | |

| metric | logistic `hit_3pct_5` / universe | / candidates | LightGBM `hit_3pct_5` / universe | / candidates |
|---|---|---|---|---|
| AUC `hit_3pct_5` (reference only) | 0.531 | 0.544 | 0.592 | 0.552 |
| precision lift (top fifth), mean | +0.029 | +0.023 | +0.040 | +0.014 |
| precision lift, non-overlapping t | 1.68 | 0.75 | 2.53 | 0.54 |
| months lift above both baselines | 6 of 10 | 4 of 10 | 7 of 10 | 4 of 10 |
| Brier skill (months above 0) | 0.0011 (5) | −0.0001 (4) | 0.0225 (9) | 0.0152 (7) |
| Brier skill after isotonic (months above 0) | | | 0.0178 (6) | 0.0190 (7) |
| mean train AUC / test AUC (universe) | 0.555 / 0.539 | | 0.660 / 0.591 | |

Logistic chose `C` = 0.001, the bottom edge of the grid and its strongest penalty, in 18 of 20 folds (0.01 twice, for `hit_3pct_5`). A wider grid would be a new secondary configuration, not a fix. LightGBM stopped after 8 to 100 rounds.

Rules of step 3, applied as fixed:
- **6-theme rerun: not triggered.** Unstable inputs: 4 of 21 for `beat_median` (`close_vs_sma20`, `sma50_change`, `return_60`, `rsi_divergence`), 2 for `hit_3pct_5` (`sma50_change`, `rsi_divergence`), below 7.
- **Smaller LightGBM: not triggered.** The gap beyond logistic's is 0.032 for `beat_median` (below 0.05). For `hit_3pct_5` it is 0.053, but LightGBM's test numbers are better than logistic's on the universe (AUC, lift t, Brier skill), so the second condition fails. On the candidates its lift t is lower (0.54 against 0.75) and its Brier skill higher.
- **Secondary replaces primary**, `hit_3pct_5`: no. LightGBM has the higher lift t on the universe (2.53 against 1.66) but is better in only 5 of 10 months, and on the candidates its t is lower. The primary stays logistic.
- **Secondary replaces primary**, `beat_median`: **no**, since the rule must hold on both populations ("Decisions", settled after these results). On the universe LightGBM has the higher IC t (1.74 against 1.56) and is better in 6 of 10 months; on the candidates it does not (t 1.48 against 2.30, better in 3 of 10).
- **Three rules named no population** when this ran: this replace rule, the smaller-LightGBM trigger and the go / no-go. Settled with the user on 2026-11-28, after seeing these numbers ("Decisions"): the go / no-go and the replace rule on both populations, the trigger on the universe (so not triggered). With that, `beat_median`'s primary misses the test-month bars (universe IC t 1.56), and nothing passes yet.

Reading (the go / no-go waits for step 4 and the hold-out):
- **A first signal on `beat_median`, from the logistic primary on the candidates:** AUC 0.529, IC t 2.30, IC above both baselines in 8 of 10 months, the three bars of the go / no-go on the test months. On the universe it falls short (AUC 0.516, t 1.56). The baselines' IC on the same months was negative (step 2), so the learned weights differ from the hand-set ones.
- **The logistic coefficients say why the score fails.** With a stable sign in every fold, the model rewards `close_vs_sma50`, `sma20_above_sma50`, `rsi14`, `ppo_histogram` and `up_down_volume_ratio`, and penalises `return_20` (short-term reversal), `return_volatility`, `turnover_ratio`, `close_location`, `close_vs_prior_high`, `higher_lows` and `candle_pattern`. The score gives points to several of the penalised ones.
- **`hit_3pct_5`:** the primary (logistic) fails every bar (lift t 1.68 / 0.75, Brier skill about 0). LightGBM reaches lift t 2.53 and a positive Brier skill in 9 of 10 months on the universe, but not on the candidates, the population Phase 2 decides.
- **LightGBM's AUC on `hit_3pct_5` is volatility, not a leak and not market timing.** It is 0.592 pooled and 0.60 or more in 5 of 10 test months (the plan's leak bar), but 0.580 within a session (mean over 199 sessions), so the market level explains little. `return_volatility` alone gives 0.591 pooled and 0.573 within a session. A volatile stock crosses +3% more often and −3% more often: by quintile of `return_volatility` on the test months, the share reaching +3% goes from 0.171 to 0.262, the share falling 3% or more from 0.161 to 0.350, and the mean 5-session return from +0.1% to −0.4% (all printed by `research/models.py`, after the `hit_3pct_5` tables). The input is computed up to t (step 1's look-ahead check), so no leak.
- **The `hit_3pct_5` logistic model ranks by volatility too:** `return_volatility` is +0.094 there against −0.099 for `beat_median`. Its rank IC against the 5-session return is −0.063 (t −2.22), top minus bottom −0.4%: it finds stocks that reach +3% more often but return less. Neither the precision lift nor the Brier skill sees that. For step 5c it means a buy on `P(hit_3pct_5)` buys volatility; the go / no-go of `hit_3pct_5` may need a return bar as well.
- **Many tries:** 8 cells (2 models × 2 labels × 2 populations, each label's main metric), 2 cross t ≥ 2 (logistic `beat_median` on the candidates, LightGBM `hit_3pct_5` on the universe), on different models and labels. Weak evidence; the hold-out decides.
- Calibration: logistic on `hit_3pct_5` is too high in every decile (0.22–0.35 against 0.18–0.26 observed: the training base rate, 0.238, is above the test months' 0.218). LightGBM's raw probabilities are also too high at the top; isotonic lowers the Brier skill on the universe (0.0225 to 0.0178) and raises it on the candidates. The calibrated numbers are approximate: the map is fitted on the inner folds' boosters (shorter windows, each at its own best round, chosen by early stopping on the very fold the map is fitted on), then applied to the final booster (whole window, mean round count). Kept as fixed before the run; a cleaner calibration would be a new secondary configuration.

**Step 4, 14 inputs from the bars (2026-11-28)**, on `out/features_step4.csv`, exported from the **local** database (prices to 2026-11-27): 41,388 rows over 401 sessions (2025-04-17 to 2026-11-27). The walk-forward is the same (2025-11 to 2026-08, 200 sessions, 20,404 rows on the universe, 5,491 on the candidates; hold-out untouched). `uv run --group research python -m research.models --extra`, about 40 s; full tables in `out/models_step4.md`. `--check --extra` passed first (shuffled labels: AUC 0.492 to 0.500; planted signal: 0.776 to 0.779), on code and plan committed before the run (`dd70e22`).

The new CSV is not step 3's, so every 21-input number below is from a rerun on it, never step 3's table. Compared with step 3's CSV before 2026-09-01: 37,360 rows in common, 48 only in the old one (the universe moved), and 784 rows differ in the 21 inputs, all of symbols whose history `vn_stock_dividend_history` re-stored adjusted since step 3 (FPT 342, BVH 320, VPX 122; the 48 old-only rows are VPX's too); through the percentiles they move 4,191 `score`s and, through the session median, 5,845 `excess_return_5` (28 `beat_median`, 1 `hit_3pct_5`). The panel now starts at the full backfill (`BACKFILL_START`, 2025-01-02): three re-stored symbols (BVH, FPT, PDN) also have bars from 2019, which would have started the panel there with 3 symbols a session. The local database has no candidate on 11 sessions from 2026-11-12 on (inside the hold-out; not looked into, the hold-out look runs on production).

`beat_median` (main metric: rank IC; non-overlapping t):

| configuration | universe AUC | universe IC t | candidates AUC | candidates IC t | months IC above both baselines (universe / candidates) | vs the primary: better months (universe / candidates) |
|---|---|---|---|---|---|---|
| **logistic, 21 (primary)** | 0.517 | 1.57 | 0.529 | 2.34 | 8 / 8 | |
| LightGBM, 21 | 0.523 | 1.75 | 0.550 | 1.43 | 8 / 8 | 6 / 4 |
| logistic, 35 | 0.522 | 2.01 | 0.528 | 2.09 | 8 / 8 | 6 / 3 |
| LightGBM, 35 | 0.529 | 2.48 | 0.552 | 1.65 | 8 / 7 | 8 / 4 |

`hit_3pct_5` (main metric: precision lift of the top fifth; non-overlapping t):

| configuration | universe lift t | candidates lift t | Brier skill (months above 0), universe | candidates | months lift above both baselines (universe / candidates) | vs the primary: better months (universe / candidates) |
|---|---|---|---|---|---|---|
| logistic, 21 (primary) | 1.65 | 0.71 | 0.0011 (5) | −0.0000 (4) | 6 / 4 | |
| LightGBM, 21 | 2.27 | 0.25 | 0.0223 (9) | 0.0157 (6) | 7 / 4 | 5 / 4 |
| **logistic, 35 (replaces the primary)** | 2.04 | 1.03 | 0.0023 (6) | 0.0008 (5) | 6 / 4 | 7 / 6 |
| LightGBM, 35 | 2.73 | 1.49 | 0.0239 (9) | 0.0153 (7) | 8 / 5 | 4 / 5 |

Rules, applied as fixed (populations as settled in "Decisions"):
- **Replace rule, `beat_median`: no.** Every secondary has the higher t on the universe and better months there, and the lower t on the candidates, better in 3 or 4 of 10. The primary stays logistic on 21 inputs.
- **Replace rule, `hit_3pct_5`: logistic on 35 inputs replaces the primary.** It has the higher lift t on both populations (2.04 against 1.65, 1.03 against 0.71) and is better in most months on both (7 and 6 of 10). The two LightGBMs are better in 5 or fewer months on at least one population.
- **Go / no-go on the test months: no for both labels.** `beat_median` (logistic, 21): AUC 0.517 and IC t 1.57 on the universe miss 0.52 and 2; the candidates pass every bar. `hit_3pct_5` (logistic, 35): the universe passes (lift t 2.04, Brier skill above 0 in 6 of 10 months, lift above both baselines in 6 of 10), the candidates fail all three (t 1.03, Brier skill above 0 in 5 of 10, lift above both baselines in 4 of 10).
- **Smaller LightGBM: not triggered** (universe). Gap beyond logistic's: 0.035 (`beat_median`, 21), 0.028 (35); `hit_3pct_5` 0.057 (21) and 0.066 (35), but there LightGBM's test numbers are better than logistic's on the universe.
- **6-theme rerun: open, depends on a reading chosen after these results.** The rule (step 3) says 7 or more "of the 21 inputs", written for the 21-input runs: those have 4 and 2. On 35 inputs, counted among the 21: 3 for `beat_median` and 4 for `hit_3pct_5`, not triggered; counted among all 35: 6 for `beat_median` (plus `return_1`, `return_5`, `limit_up_days`) and **7** for `hit_3pct_5` (plus `return_5`, `amihud`, `max_return_20`), triggered for that label. To settle with the user; the themes hold only the 21 inputs anyway.

Reading:
- **Logistic on 35 inputs would pass `beat_median`'s go / no-go on both populations** (AUC 0.522 / 0.528, IC t 2.01 / 2.09, 8 of 10 months above both baselines on each), but the replace rule keeps the primary, because on the candidates it is better than the primary in only 3 of 10 months. The rule decides, as fixed; to say so is not to change it.
- **The new inputs with a stable sign in every fold (logistic, `beat_median`):** lower `max_return_20` (lottery effect), deeper `drawdown_60` (further below the 60-session high), lower `amihud`, fewer `limit_down_days`, higher `gap`, lower `range_pct` and shadows, higher `volume_change_1`. `return_1` and `return_5` are unstable: no clear short-term reversal beyond `return_20`'s. LightGBM's largest gain on `beat_median` is `max_return_20`, ahead of `return_volatility` and `return_60`.
- **`hit_3pct_5` still buys volatility:** among the 35-input logistic's largest weights are `drawdown_60` (−0.081, the largest), `range_pct` (+0.059) and `return_volatility` (+0.056), next to `rsi14` and `sma20_above_sma50`; its rank IC against the 5-session return is −0.053 (t −1.83, universe), as step 3 found for the 21 inputs.
- **Many tries:** 16 cells now (4 configurations × 2 labels × 2 populations, each label's main metric), 7 cross t ≥ 2, none of them on the candidates of `hit_3pct_5`. Weak evidence; the hold-out decides, once per label.
- **These numbers are provisional: they come from the local database.** On the same model, the two databases already differ by about the margins the rules turn on (LightGBM on 21 inputs, `hit_3pct_5`, universe lift t: 2.53 on step 3's production CSV, 2.27 here), and the `hit_3pct_5` replacement rests on 2.04 against 1.65 and 7 / 6 months. So, fixed before any production number exists (2026-11-28): the same command on a production export (`DATABASE_URL=<production> uv run python -m research.export_features out/features_step4.csv`, then `uv run --group research python -m research.models --extra`) replaces this table, and its numbers decide the replace rules and the go / no-go. The hold-out look, if run, scores the kept configurations it names.
