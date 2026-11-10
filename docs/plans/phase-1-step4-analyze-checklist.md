# Phase 1, step 4 — `vn_stock_analyze`: detailed checklist (for review)

Status: **all review questions answered, ready to build** (2026-11-10). Expands step 4 of [phase-1-sql-screens.md](phase-1-sql-screens.md); the indicator table, definitions, gates and output contract stay defined there. This file only says **how to build it, in which order, and how to test it**.

## Decided (2026-11-10)

- Prices are already in the database. Locally the data comes from `data/seeds/` (migration `0003_seed_prices`, 2025-01-02..2026-11-06, about 460 sessions per symbol), so no backfill task blocks this step.
- The batch upsert is already done in the store script.
- `vn_stock_get_history` stays a **separate job** (not merged into `vn_stock_screen`): each job's logic must be changeable on its own.
- **TA-Lib** is the indicator library, including its candle patterns for #23 (see Q1 for what that changes).
- Dependabot / `pip-audit` schedule: later, not in this step.
- Candle patterns: TA-Lib as is. Its gap-based morning star / piercing line will rarely fire on HOSE; the gap handling is fixed later in a different pipeline.
- Layout: many small modules under `libs/analysis/`; the script only calls them (easier to review).
- Local run: on a trading day run the real sync (retrieval + store) after `alembic upgrade head`; otherwise copy the last stored session to today (README has both); production code gets no new switch, no `AS_OF`.
- Percentile-rank indicators (#6, #7, #20) depend on the whole shortlist; accepted.
- **Data from Postgres is taken as correct (2026-11-10).** No re-validation in `vn_stock_analyze`: no market calendar, no "no bar today" / "missing previous session" lists, no missing-session gate, no corporate-action detection (the history is kept adjusted and complete on the data side). Each history file is ascending and ends on the session analysed (the screen requires a bar today); `as_of` = the newest date. This supersedes the "Missing session" and "Corporate action" rows of the plan's Gates table and the `suspected_corporate_action` flag. What stays: too few rows → indicator `unavailable` → coverage gate (that is real variation, not bad data).
- #22–#24 ship together with #1–#21 (slice F after E, same feature); the coverage gate stays on the full 100 points.

## Design rules (so each piece can change alone)

- **Three layers, three places**, so tuning one never touches the others:
  1. *raw features*: pure functions `(rows) -> raw values or None` (SMA gap, RSI, PPO histogram, …). Know nothing about points.
  2. *scoring config*: one table (id, theme, max points, lo/hi thresholds, direction, min rows). Changing a weight or a threshold edits one row.
  3. *gates and flags*: coverage, uptrend, flags. Separate functions, not inside the indicators.
- The job only reads the `vn-stock-history` artifact (no DB, no network) and writes `out/vn_stock_analysis.json`. Phase 2 reads only that JSON.
- NaN never leaves the TA-Lib boundary: convert to `None` ("unavailable") in one helper.
- Pure functions on plain lists / small pydantic models; numpy arrays only inside the TA-Lib wrapper.

Layout (decided):

```
libs/analysis/models.py       output pydantic models (the stable contract)
libs/analysis/indicators/     Indicators interface (base.py) + TalibIndicators (talib_engine.py), the only talib / numpy import; features get the engine injected, a new library = a new subclass
libs/analysis/features.py     raw feature functions
libs/analysis/scoring.py      config table, ramp(), percentile rank, assert sum == 100
libs/analysis/gates.py        coverage gate, uptrend gate, flags
scripts/vn_stock_analyze.py   load -> features -> gates -> score -> rank -> JSON + summary table
tests/libs/analysis/…, tests/scripts/test_vn_stock_analyze.py
```

## Slices (one PR each, in this order)

### A. Dependency and local data

- [x] Add `TA-Lib` to the **runtime** dependencies in `pyproject.toml` (not the dev group: the workflow installs `--no-dev`); refresh `uv.lock`; check `uv sync --locked --no-dev` works on macOS arm64 and on the CI Linux runner.
- [~] Verify the wheel bundles the C library (no system `ta-lib` needed) and that `import talib` works in the `install` job; update the README cache note if the `runtime` cache key or size changes. (done locally: `uv sync --locked --no-dev` + `import talib` on macOS arm64, `uv.lock` has the manylinux x86_64 cp312 wheel; the CI `install` job still to confirm on the PR)
- [x] Local run recipe in the README: `docker compose up -d`, `uv run alembic upgrade head` (loads the seed), then screen → history → analyze.
- [x] **Local row for today.** `vn_stock_screen` fails unless the newest session is today (VN) and at least 90% of the previous session's symbols have a bar today; the seed ends 2026-11-06. Locally, copy the newest session to today and run the pipeline normally. One documented SQL statement in the README, no script, no code change:

  ```sql
  INSERT INTO prices (symbol, date, source, unit, open, high, low, close, volume)
  SELECT symbol, CURRENT_DATE, source, unit, open, high, low, close, volume
  FROM prices WHERE date = (SELECT max(date) FROM prices)
  ON CONFLICT (symbol, date) DO NOTHING;
  ```

  Caveats to write next to it: a copied bar means 0% change and the same volume (fine for a smoke run, not for judging scores); on a weekend `CURRENT_DATE` is not a session, so set the date by hand; delete the copied rows afterwards (`DELETE FROM prices WHERE date = CURRENT_DATE`) before running the real sync against that database.

### B. Output contract (models first, so Phase 2 can be reviewed against it)

- [x] `AnalysisReport`: `as_of`, `universe_size` (the shortlist is `len(symbols)`, e.g. 120 of 406), counts (`scored`, `insufficient_data`, `flagged`), `sources` used, `symbols` list.
- [x] `SymbolResult`: `symbol`, `score` (None when the coverage gate fails), `coverage` (available points), `status` (`scored` / `insufficient data`), theme subtotals, `indicators`, `flags`, turnover (for the tie-break).
- [x] `IndicatorResult`: `id`, `points`, `max`, `raw` (dict of the raw values named in "Output per symbol"), `status` (`scored` / `gate_closed` / `unavailable`).
- [x] Flags enum: `ceiling_locked`, `new_listing`, `low_coverage`. Flags never change the score.
- [x] `extra="forbid"` and an example JSON checked into `tests/data/` so a contract change is a visible diff.

### C. Loading

- [x] Read `out/vn_stock_history/*.json` with the existing `read_prices`; one `list[Price]` per symbol (`scripts/vn_stock_analyze.py: load_history`).
- [x] `as_of` = the newest date in the history. Indicators work on **rows** (the preceding session is the previous row).
- [x] Empty or missing history folder → exit `NO_DATA` (4), like the other jobs.

### D. Gates (small: they only decide what counts, never repair data)

- [x] Coverage gate: score only when available points ≥ 80, else `insufficient data` with no number.
- [x] Uptrend gate for #22, #23: closed (0 points, `gate_closed`) when the raw value of #4 < 0; `unavailable` when #4 itself is unavailable.
- [x] Flags (shown, never change the score): `ceiling_locked` (close within 0.5% of +7%), `new_listing` (`listed_date` in `data/hose_symbols.csv` less than 90 calendar days before `as_of`, about 60 sessions), `low_coverage` (available points < 90). Constants named in `libs/analysis/gates.py`.
- [x] Tests: coverage edge (exactly 80), gate closed vs unavailable, each flag.

### E. Indicators (#1–#21), in groups so each group is a reviewable commit

Each indicator = raw function + config row + test on a **small hand-computed series** (TA-Lib golden values would be circular).

- [x] Scoring core: `ramp(x, lo, hi, direction)`, yes/no, percentile rank, config table, `assert sum(max) == 100`, available-points calculation.
- [x] Trend #1–#5: `talib.SMA`; #3 yes/no; #4 SMA50 vs 10 sessions ago.
- [x] Momentum #6–#7 (percentile rank across the shortlist: needs a second pass after all raws exist), #8 `talib.RSI(14)` with the trapezoid ramp, #9–#11 PPO recipe: `talib.PPO(close, 12, 26, matype=1) / 100`, histogram = ppo − `talib.EMA(ppo, 9)` on the non-NaN part (**not** `talib.MACD`), #11 cross recency.
- [x] Money flow #12–#15: up-day-only volume ratio, up/down-volume ratio (full points when no down-volume), 5/20 turnover ratio, close location (unavailable when high = low).
- [x] Position #16–#18: prior 20-session high (excluding today), 250-session high, higher lows.
- [x] Risk #19–#21: overextension, `talib.STDDEV` of daily returns + percentile rank (#20), distribution-day yes/no.
- [~] Re-measure the warm-up min rows (#8 45, #9 70, #10 55, #11 70) against the seed's real history: **deferred to the tuning pass** (with the weights and thresholds); the plan's values are in the table.
- [x] Check the seed for symbols with too little history (new listings) → `insufficient data` path exercised on real data.
- Notes (decided while building): all 24 rows are in `libs/analysis/scoring.py` from now, #22–#24 are `not_built` stubs (unavailable) until slice F, so with only #1–#21 the most a symbol can have available is 86 points: before F nobody below about 200 rows passes the 80-point gate, by design. Availability is decided by `min_rows`, not by NaN (TA-Lib returns RSI / EMA values long before the warm-up the table asks for). Percentile rank: ties share the middle, one symbol alone = 0.5. Smoke run on the 88 real history files: no exception, no non-finite value, LPS (58 rows) 63 points available, GEL (187) 78, VCK (223) 84, the rest 86.

### F. Indicators #22–#24 (the heavy ones)

- [x] #23 candle patterns with **TA-Lib** through the engine interface (`Indicators.bullish_patterns`: `CDLENGULFING`, `CDLHAMMER`, `CDLMORNINGSTAR`, `CDLPIERCING`), strength 1.0 / 1.0 / 1.0 / 0.8 / 0.7 as in the plan, volume factor, recency factor, skip `high == low`, 5-session ≤ −3% context. The plan's gap-free hand-written variants are dropped (Q1).
- [x] #22 RSI bullish divergence: pivots (3 before / 3 after on close), latest two pivot lows within 40 sessions and ≥ 5 apart, conditions and recency per the plan; raw value = dates and RSI of L1 and L2.
- [x] #24 descending trendline breakout: pivot highs, candidate lines on `ln(high)` over the 60 sessions ending t−3, validity check (no high above the line by > 0.5%), choose by touches / length / recency, breakout on t−2..t, recency, volume and touches factors; raw value = anchor pivots, `L(t)`, touches.
- [~] Plot the detected trendlines and divergences for about 20 real symbols once (throwaway script, not committed) before trusting the weights: **deferred to the tuning pass**.
- Notes (decided while building): code in `libs/analysis/patterns.py` (a `Detection` = strength + facts); the uptrend gate is applied in `score_indicators` (`uptrend_only` rows read #4's raw value). Facts are given as *sessions ago* (the history carries no dates), e.g. `l1_sessions_ago`, `l2_rsi`, `touches`, `line_today`. The trendline's breakout volume is the breakout session's, not always today's. #22 pairs the latest pivot low with the latest one at least 5 sessions before it. Smoke on the 88 real files (TA-Lib engine): #22 fires on 8, #24 on 1, #23 on none (7 engulfing / 2 hammer / 1 morning star / 3 piercing flags in the last 3 sessions, none after a 3% fall: the market had been rising). The line plots for about 20 symbols are not done: to do with the tuning pass.

### G. Ranking, output, summary table

- [ ] Sort by score (desc), ties by turnover (desc); `insufficient data` symbols after the scored ones.
- [ ] Write `out/vn_stock_analysis.json` from the pydantic model (the directory is emptied / the file removed first, like the other scripts, so an old file never passes for today's).
- [ ] Markdown table to `$GITHUB_STEP_SUMMARY`: rank, symbol, score, coverage, five theme subtotals, flags; a header line with `as_of`, shortlist size, counts. Local runs print the same table to stdout instead.
- [ ] Logging through `Logger` (never `print`); log counts of scored / insufficient / flagged.
- [ ] Exit codes: 0 ok, 4 no data, anything else = crash (same convention).

### H. Workflow job

- [ ] Job `vn_stock_analyze` in `.github/workflows/vn-stock-analysis.yml`: `needs: [install, is_holiday, vn_stock_get_history]`, **no** `environment` and no `DATABASE_URL`.
- [ ] Download artifact `vn-stock-history` into `out/vn_stock_history`, run `uv run --no-sync python -m scripts.vn_stock_analyze`, upload `vn-stock-analysis` (the JSON), write the summary table.
- [ ] End with the `pipeline-state` action (success / failure messages), add the job to `notification`'s `needs`.
- [ ] Check the `uv` cache rule is respected (`prune-cache: false`, only `install` saves).
- [ ] Job timeout and artifact retention consistent with the other jobs.

### I. Tests and "done when"

- [ ] One test per indicator, per gate, and the cases that remain: halted symbol (volume 0 / high = low), too little history, every gate.
- [ ] Contract test: the JSON validates against the model and equals the example file's shape.
- [ ] End-to-end test on `tests/data/prices_hpg_aam.json` (real HPG and AAM): AAM is almost untraded, HPG is very liquid.
- [ ] Manual run: local Postgres seeded → today's copied row → screen → history → analyze → eyeball the top 10 against a chart of 3 symbols.
- [ ] Real `workflow_dispatch` run shows the score table in the job summary; a day off skips the job.
- [ ] `uv run pytest` ≥ 95% coverage, `ruff` clean.

### J. Documents

- [ ] Phase 1 plan: tick step 4 and 5, fix the stale Assumption (line 47 says the table only has days since 2026-10-27; it now has the seed back to 2025-01-02), update Open questions 1, 4, 5, 6 with today's decisions.
- [ ] README: add `vn_stock_analyze` to the workflow's jobs, the new scripts to the file tree, the local-run recipe (seed, today's row).
