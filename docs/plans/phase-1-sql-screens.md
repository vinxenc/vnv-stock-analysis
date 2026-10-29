# Phase 1 — Screens and analysis (no LLM)

Status: **draft checklist for discussion** (2026-10-28). Next phase: [phase-2-llm-summary.md](phase-2-llm-summary.md).

Option 1 = "build a short list from the data, then one LLM call writes the summary", split into 2 phases: **Phase 1 has no LLM**, Phase 2 adds the LLM call.

## Decisions and open items

Decided by the user:
- New pipeline, not a replacement: the existing sync workflow keeps filling `prices`, now at 20:00 VN (it was 22:00); the analysis is a second workflow.
- Schedule: GitHub Actions only, 15:00 UTC (22:00 Vietnam), Mon–Fri. `is_holiday` checks **today**: a day off → the rest is skipped, otherwise the later jobs run. The session analysed is today's (the market closed at 15:00 VN).
- Ordering: the sync runs at 20:00 VN and takes about 20 min, the analysis starts at 22:00 VN, so the prices are stored well before. A late or failed sync is caught by the date check in `vn_stock_screen`.
- Liquidity filter: **average** turnover (`close × volume`) over the last **20 sessions** ≥ **20 billion VND** (changed from the latest session only, 2026-10-29).
- Jobs: `vn_stock_screen`, `vn_stock_get_history` (reads the existing DB, never writes), `vn_stock_analyze`; the LLM job comes in Phase 2.
- Ranking: one composite score 0–100, buy side, trend / breakout profile, the 24-indicator table below.
- Library for the indicators: **TA-Lib** (see "Libraries").

Open, for the next session to decide:
- The ponytail simplification suggestions ("Simplification suggestions" below, none applied).
- Candle patterns: hand-written gap-free versions or TA-Lib's gap-based ones.
- Who fills the history in `prices`, and when.
- Weights, thresholds and the listing threshold, after the real score distribution is visible.

## Flow

```
existing workflow "VN Stock Prices Sync" (vn-stock-prices-sync.yml), unchanged: cron 20:00 Vietnam (13:00 UTC), Mon–Fri
  … → retrieve_prices → vn_stock_daily_price_store      latest bar of all 406 symbols → prices

NEW workflow "VN Stock Analysis" (vn-stock-analysis.yml): cron 15:00 UTC = 22:00 Vietnam, Mon–Fri (two hours after the sync)
  start-analyze → install → is_holiday (is TODAY a working day?)
    → vn_stock_screen        drop illiquid symbols      → shortlist (artifact)
    → vn_stock_get_history   history of the shortlist, read from the DB → history (artifact)
    → vn_stock_analyze       features, signals, ranking → JSON artifact + job summary
    → notification
```

The new workflow fetches nothing: it reads the bar of today's session from `prices`, which the sync workflow stores. The sources never return a Saturday session (HOSE is closed).

Out of scope for Phase 1: the LLM call (Phase 2), an agent that explores the data, Telegram / email (GitHub job summary only), news and financial statements (only the `prices` table), and **filling the history in `prices`** (assumed done, see Assumptions).

## Assumptions

- `prices` already holds enough history for the shortlisted symbols (the length is set in step 3). Backfilling it is a separate task, not part of Phase 1. Today the table only has the days stored since 2026-10-27, so until a backfill runs (61 rows are needed to get a score), every symbol will be `"insufficient data"`.

## Checklist

Every new job follows the existing pattern: `environment: production` when it needs `DATABASE_URL`, ends with the `pipeline-state` action, is added to `notification`'s `needs`, logs through `Logger` (never `print`), has type hints, and keeps the 95% coverage gate.

### 1. Everything runs on GitHub Actions at 22:00 Vietnam time (15:00 UTC), Mon–Fri

- [x] Rename `vn-stock-analysis.yml` to `vn-stock-prices-sync.yml` (it is the "VN Stock Prices Sync" workflow), only the cron changes, `0 15 * * 1-5` (22:00 VN) → `0 13 * * 1-5` (20:00 VN); retrieve + store only. It stays the only writer of `prices`.
- [x] Add a new workflow `vn-stock-analysis.yml`, named `VN Stock Analysis`, cron `0 15 * * 1-5` (15:00 UTC = 22:00 Vietnam, same calendar day), plus `workflow_dispatch`. Same shape as the sync workflow: `start-analyze` → `install` → `is_holiday` → jobs below → `notification`. No `retrieve_prices` and no store job: it only reads `prices`. Reuse the composite actions (`pipeline-state`) and the `uv` cache rule from the README (`prune-cache: false`, only `install` saves the cache).
- [x] The new workflow has its own `is_holiday` job (copy of the sync workflow's, same script) that checks **today** (VN): weekend or public holiday → the rest of the pipeline is skipped; working day → it proceeds.
- [x] `scripts/vn_holiday.py` is unchanged (exit 0 = day off, 3 = working day). The new workflow's `is_holiday` only decides whether the later jobs run: day off → skipped, working day → they proceed. No `session_date` output; the session analysed is today (VN).
- [x] `vn_stock_screen` fails if `max(date)` in `prices` is not today (VN) (the sync failed, has not finished yet, or the source is stale), instead of reporting old data as fresh. `vn_stock_analyze` takes the same date from the screen's output.
- [x] Nothing runs outside GitHub Actions: no local cron, no extra server.
- [ ] Time budget: no retrieval in this workflow, so the whole run should take only a few minutes and finish well before the 09:00 open. GitHub may delay scheduled runs, so keep the margin.
- [x] Update the README: add the new workflow to the files table and its jobs; the sync workflow's description now says 20:00.

### 2. `vn_stock_screen` — drop illiquid symbols (SQL on the latest trading day)

- [x] Job `vn_stock_screen`, `needs: is_holiday`, uses `DATABASE_URL` (ideally a read-only role).
- [x] Check `max(date)` = today (VN) (see 1); otherwise fail.
- [x] SQL: turnover = `close × volume` (thousand VND). Keep symbols with a row today whose **average turnover over their last 20 rows ≥ 20 billion VND per day** = 20,000,000 thousand VND. Keep the threshold as one named constant in the script.
- [x] Symbols with `volume = 0` (halted) drop out naturally; log how many were kept and dropped.
- [ ] **Before trusting the threshold, verify the volume definition.** VNDirect's `nmVolume` is matched volume only (no put-through trades); DNSE and VPS `v` must be the same unit (shares) and definition, otherwise a symbol's turnover changes with whichever source answered that day. Compare one liquid symbol on the same day across the 3 sources.
- [ ] Market-wide numbers are computed here, because only this job has all 406 symbols: over every symbol that has a row on today's session and on the preceding session, one SQL aggregate for advancers / decliners / unchanged, total volume, total turnover, and the median one-day change. `vn_stock_analyze` cannot compute them from the shortlist history.
- [x] Output artifact `vn-stock-screen` (done with `liquid_symbols.csv` only; `market.json` deferred, simplification suggestion 2) with two files: `liquid_symbols.csv` (a `code` column, same shape as `data/hose_symbols.csv`, so `read_symbols` is reused) and `market.json` (the numbers above).
- [x] Exit 4 (the existing "no data" code) when the shortlist is empty; the job then fails.
- [x] Tests on the real Postgres fixture: threshold edge (exactly 20 billion kept), halted symbol, wrong `max(date)`.
- [ ] Look at the real shortlist size once with real data (20 billion is a high bar; expect a fraction of the 406).

### 3. `vn_stock_get_history` — read the history of the shortlist from the DB

- [ ] Job `vn_stock_get_history`, `needs: vn_stock_screen`, uses `DATABASE_URL` (read-only role is enough). It reads, it never writes.
- [ ] Download the `vn-stock-screen` artifact, select the last N sessions of those symbols from `prices` (ascending by date), and upload artifact `vn-stock-history` (symbol, date, open, high, low, close, volume, source). `vn_stock_analyze` then needs no DB access.
- [ ] N sessions: **260 recommended**. The longest lookbacks of the scoring table decide it (#5 needs 200 rows, #17 needs 250, plus a buffer). With 120 the score still works but #5 and #17 (8 points) are unavailable. See "Minimum history" in the scoring design.
- [ ] Log symbols that have fewer than N rows. Missing rows are reported, never fatal; the analysis decides what to skip.
- [ ] Exit 4 when no row is found.
- [ ] Tests on the real Postgres fixture.

### 4. `vn_stock_analyze` — indicators, gates, score (heaviest)

- [ ] Job `vn_stock_analyze`, `needs: vn_stock_get_history`, no DB secret. Inputs: the `vn-stock-history` artifact and `market.json` from `vn-stock-screen` (whole-market breadth, volume and median change; they go into the output for the summary, no indicator uses them).
- [ ] Stages, as plain functions in one job: load and validate → features per symbol → signal flags → ranking → output.
- [ ] Libraries: TA-Lib (runtime dependency) for the standard indicators, stdlib for everything else. Details, verified facts and open points in "Libraries".
- [ ] Computation by **rows**, never calendar dates (holidays). A symbol must have a row on today's session; keep only symbols with a row on the preceding session too, put the others in a "missing previous session" list and count them. An indicator with too little history is `unavailable` and a symbol below the coverage gate is `"insufficient data"` (see Scoring design); neither is ever a failure.
- [ ] When a one-day change is beyond the HOSE band (±7%, to be verified), label the symbol "suspected corporate action" **and exclude it from every feature whose window contains that day** (returns, moving averages, highs/lows, volume average); otherwise one ex-rights day skews its features for 20–50 sessions. See Notes.
- [ ] Output `out/vn_stock_analysis.json` (pydantic model; Phase 2 reads it, so keep it stable): `as_of`, shortlist coverage (e.g. 120 of 406 symbols), counts of `insufficient data` and flagged symbols, sources used, the whole-market numbers from `market.json`, and one entry per symbol as described in "Output per symbol". Upload it as artifact `vn-stock-analysis`.
- [ ] Render the ranked symbols (score, coverage, theme subtotals, flags) and the market numbers as markdown tables into `$GITHUB_STEP_SUMMARY`.
- [ ] Tests: holiday gap, missing session, halted symbol, too little history, a fake drop, every gate, and one test per indicator.
- [ ] Ranking = **one composite score per symbol, 0–100, buy side first** (trend / breakout profile). The indicator table, gates and output are in "Scoring design" below. In code: one config table (id, theme, max points, thresholds, direction, minimum rows), an assertion that the maximums add up to exactly 100, one small pure function per indicator, and a test per indicator.

### 5. Done when

- [ ] A manual run against a local DB with fake data gives the right shortlist, history and JSON.
- [ ] A real `workflow_dispatch` run shows the score table in the job summary.
- [ ] A day off: all jobs after `is_holiday` are skipped. A failed sync (no bar for today): `vn_stock_screen` fails instead of reporting old data. The sync workflow's cron and jobs are unchanged.
- [ ] `uv run pytest` ≥ 95% coverage, ruff clean.

## Scoring design (buy side, trend / breakout profile)

The score is a **screening score**, not a buy recommendation. Every number below that is a threshold or a weight is a **placeholder** to be tuned once the real distribution is visible. A pullback / oversold-bounce profile would be a separate table later.

### Mechanics

- 24 indicators in 6 themes; every indicator scores between 0 and its maximum (never negative); the maximums add up to exactly 100 (assert in code). A "risk" indicator earns points for *not* being overextended or volatile.
- Default curve: a linear ramp, `points = max × clamp((x − lo) / (hi − lo), 0, 1)`, with a direction flag for "lower is better". Yes/no only where the concept is yes/no (#3, #21). Percentile rank is used only for comparing symbols (type R); everything else is an absolute threshold (type A).
- Rows are trading sessions, never calendar days. Prices are the adjusted prices stored in `prices`.

### Indicator table (total = 100)

| Theme | # | Indicator | Scoring (placeholders) | Pts | Type | Min rows |
|---|---|---|---|---|---|---|
| **Trend (23)** | 1 | Close vs SMA20 | 0% → +3% above | 3 | A | 20 |
| | 2 | Close vs SMA50 | 0% → +5% above | 5 | A | 50 |
| | 3 | SMA20 > SMA50 | yes/no | 4 | A | 50 |
| | 4 | SMA50 rising | SMA50 vs 10 sessions ago, 0% → +2% | 5 | A | 60 |
| | 5 | Close vs SMA200 | 0% → +10% above | 6 | A | 200 |
| **Momentum (20)** | 6 | 20-session return | percentile rank in the shortlist | 5 | R | 21 |
| | 7 | 60-session return | percentile rank in the shortlist | 4 | R | 61 |
| | 8 | RSI(14) in the 55–70 zone | 0 at ≤ 40 ramping to full at 55, full to 70, ramping to 0 at ≥ 85 | 2 | A | 45 |
| | 9 | MACD histogram > 0 | PPO histogram, 0 → +0.5% | 4 | A | 70 |
| | 10 | MACD histogram rising | change vs 3 sessions ago, 0 → +0.3% | 3 | A | 55 |
| | 11 | MACD fresh bullish cross | only while the histogram is > 0; full if crossed within 1 session, 0 after 6 | 2 | A | 70 |
| **Money flow (25)** | 12 | Volume vs 20-session average, up days only | 1× → 2× (0 on a down day) | 8 | A | 21 |
| | 13 | Up-volume / down-volume over 20 sessions | 1× → 2×; full points when there was no down-volume | 7 | A | 21 |
| | 14 | Turnover: 5-session average / 20-session average | 1× → 1.5× | 5 | A | 21 |
| | 15 | Close location in the day's range | (close − low) / (high − low), 0.5 → 0.9; unavailable when high = low (locked at the ceiling or floor) | 5 | A | 1 |
| **Position (12)** | 16 | Close / previous 20-session high | 0.93 → 1.0 | 2 | A | 21 |
| | 17 | Close / 250-session high | 0.75 → 0.95 | 2 | A | 250 |
| | 18 | Higher lows | lowest low of the last 10 sessions vs the 10 before, 0% → +3% | 4 | A | 20 |
| | 24 | Descending trendline breakout | see definitions | 4 | A | 70 |
| **Risk (10)** | 19 | Not overextended | full at ≤ +8% above SMA20, 0 at ≥ +18% | 4 | A | 20 |
| | 20 | Low volatility | std dev of daily returns over 20 sessions, lower is better, percentile rank | 3 | R | 21 |
| | 21 | No distribution day in the last 10 sessions | yes/no; a day with a drop ≥ 3% on volume ≥ 1.5× average voids it | 3 | A | 21 |
| **Reversal (10), gated** | 22 | RSI bullish divergence | see definitions | 5 | A | 60 |
| | 23 | Bullish reversal candle pattern | see definitions | 5 | A | 60 |
| | | **Total** | 23 + 20 + 25 + 12 + 10 + 10 | **100** | | |

About three quarters of the points come from price (trend, momentum, position, risk) and a quarter from volume and money flow; for this profile that is intended, and the money-flow block is the independent check. "MACD line > 0" is deliberately absent: it equals EMA12 > EMA26, a faster version of #3.

### Definitions

**MACD (#9–#11).** Normalised by price so symbols of any price level compare: `PPO = (EMA12 − EMA26) / EMA26`, `signal = EMA9 of PPO`, `histogram = PPO − signal`. EMAs are seeded with the SMA of the first n closes and run over the whole history window. **Warm-up rule for every EMA / Wilder-based indicator (#8–#11, #22).** Their value depends on how many rows are fed in. Run the indicator on the last L rows and on 1500 rows of 300 synthetic random walks, convert the difference into score points through the indicator's own ramp, and take the smallest L where the 99th-percentile error is ≤ 0.5 point. Measured: #8 45 rows, #9 70, #10 55, #11 70, #22 60 (the min-rows column; measured on synthetic prices, to be re-measured on real history). For reference, the raw PPO histogram error is 0.03% of price at 61 rows against a typical histogram of 0.43%, i.e. strict "trust" would need about 100 rows, but that is stricter than the score needs.

**RSI (#8).** Wilder RSI(14), seeded with the average of the first 14 changes (identical to TA-Lib at any row, verified).

**#22 RSI bullish divergence (regular).**
- Pivot low = a session whose `close` is lower than the 3 sessions before and the 3 after it. Confirmation needs 3 sessions after the pivot, so the signal always **lags by about 3 sessions**.
- Take the two latest pivot lows L1 (older) and L2 (newer) within 40 sessions and at least 5 sessions apart.
- Conditions: `close(L2)` at least 1% below `close(L1)`; `RSI(L2) > RSI(L1)`; `RSI(L1) ≤ 45`; now `close > close(L2)` and `RSI > RSI(L2)`.
- Points = max × ramp of `RSI(L2) − RSI(L1)` over 0 → 8 × recency (full when L2 is within 10 sessions, falling linearly to 0 at 25 sessions).
- Raw value in the output: the date and RSI of L1 and L2.
- Option not in the table: the *hidden* bullish divergence (higher low in price, lower low in RSI) fits an uptrend better; the regular divergence mostly signals leaving a downtrend and will rarely fire under the uptrend gate. Count how often each fires once history exists.

**#23 Bullish reversal candle pattern.** Four patterns, defined on the candle bodies and **without gap rules** (HOSE opens through the ATO auction, so textbook gaps almost never occur):
- *Bullish engulfing:* previous candle bearish, this one bullish with `open ≤ previous close` and `close ≥ previous open`.
- *Morning star (3 candles):* a long bearish body, then a small body (≤ 30% of the first body), then a bullish candle closing above the midpoint of the first body.
- *Piercing line:* a long bearish body, then a bullish candle with `open ≤ previous close` closing above the midpoint of the previous body but below the previous open.
- *Hammer:* lower shadow ≥ 2× the body, upper shadow ≤ 1× the body, body in the upper part of the range.
- Context: the 5-session return before the pattern is ≤ −3%.
- Only the strongest pattern counts: engulfing and morning star 1.0, piercing line 0.8, hammer 0.7. Multiply by 1.0 if the last candle's volume ≥ 1.2× the 20-session average, otherwise 0.6, and by recency (completed today 1.0, one session ago 0.6, two sessions ago 0.3). Points = 5 × all factors.
- Raw value in the output: the pattern name and the date. Skip any candle with `high == low` (locked at the ceiling or floor).

**#24 Descending trendline breakout** (a "diagonal resistance"). The line is built and validated on the 60 sessions ending at t−3, so a breakout in the last 3 sessions cannot invalidate its own line; the breakout is tested on t−2, t−1 and t.
1. Pivot highs: `high` above the 3 sessions before and the 3 after (so the latest usable pivot is at t−6).
2. For each pair of pivot highs at least 8 sessions apart with a falling line (x = session index, y = `ln(high)`), keep the line only if no `high` between the first pivot and t−3 exceeds it by more than 0.5%.
3. Choose one line: most touches (other pivot highs within ±1% of it), then the longest, then the most recent.
4. Extend it to today to get `L(t)`.
5. "Just broke out": the breakout session b is the first session in t−2..t with `close(b) ≥ L(b) × 1.01` while the close just before it was below `L × 1.01`. Recency factor by b: t 1.0, t−1 0.6, t−2 0.3 (as #23). The breakout must still hold, `close(t) ≥ L(t)`, and must not have run far, `close(t) ≤ L(t) × 1.07`.
6. Multiply by 1.0 if volume ≥ 1.5× the 20-session average, otherwise 0.6; by 1.0 for ≥ 3 touches, 0.7 for 2.
- Raw value in the output: the dates and highs of the two anchor pivots, `L(t)`, the number of touches.
- Known limits: subjective (the rule only makes the line stable from day to day), late by the pivot confirmation, and fake breakouts are common. Check about 20 symbols by plotting the detected lines once history exists, before trusting the weight.

### Libraries (decided: TA-Lib)

- **Decision:** TA-Lib (`TA-Lib` 0.8.2 on PyPI, requires numpy) for the standard indicators, stdlib for the rest. The review recommended stdlib only (see the comparison below); that stays a valid fallback.
- **Packaging:** add `TA-Lib` to the **runtime** dependencies in `pyproject.toml` (the workflow installs with `--no-dev`), refresh `uv.lock` (CI uses `--locked`), and expect `pip-audit` to cover numpy and TA-Lib too. The wheel bundles the C library (cp312: manylinux x86_64 4.1 MB, macOS arm64 3.3 MB); numpy adds 16.7 MB on Linux. The README's uv cache rules apply (the `runtime` cache key follows `uv.lock`).
- **Use TA-Lib for:** SMA (#1–#5), EMA, RSI(14) (#8, #22), the PPO line (#9–#11), STDDEV (#20), and the candle patterns that fit (engulfing, hammer).
- **Stdlib for the rest:** pivots (#22, #24), the trendline search, percentile rank (#6, #7, #20), ramps, gates, coverage.
- **Checked** once in a throwaway environment on synthetic prices (nothing was kept; re-verify when implementing):
  - `talib.EMA` and `talib.RSI` equal the plan's definitions at every row (SMA-seeded EMA; Wilder RSI seeded with the average of the first 14 changes): every row of 50 series of 300 rows, maximum difference about 1e-13. `SMA` too.
  - `talib.MACD` does **not**: it is absolute (not price-normalised) and seeds its fast EMA differently, so it agrees with the plan only after about 150–200 rows. Use `ppo = talib.PPO(close, 12, 26, matype=1) / 100`, then `histogram = ppo - talib.EMA(ppo, 9)` on the non-NaN part. This reproduces the plan's PPO histogram (maximum difference 7e-18).
  - `talib.CDLMORNINGSTAR` and `talib.CDLPIERCING` fired only on patterns **with a gap** and returned 0 on the gap-free variants; `CDLENGULFING` and `CDLHAMMER` fired as expected (one hand-built example per case, not a statistical test). The plan defines all four gap-free because HOSE opens through the ATO auction. Open: hand-write morning star and piercing line (a few lines of stdlib each), or accept TA-Lib's gap-based definitions, which will rarely fire on HOSE.
- **Boundary:** TA-Lib returns numpy arrays padded with NaN. Convert NaN to `None` ("unavailable") at the boundary and keep pydantic models for results (README code rules).
- **Warm-up table:** the min-rows column was measured with stdlib prototypes whose EMA, RSI and PPO equal TA-Lib's, so it holds. Re-measure only if `talib.MACD` is used instead of the PPO recipe above.
- **Tests:** golden values from TA-Lib are circular when TA-Lib is also the runtime library. Test the wiring (thresholds, NaN → `None`, gates, ramps) on small hand-computed series, and use hand-built candles for the gap-free patterns.

Comparison behind the decision (PyPI wheels for Linux x86_64; `uv.lock` has none of numpy, pandas, polars or scipy today):

| Library | Added to the runtime | Measured / checked |
|---|---|---|
| stdlib | 0 | 26 lines for SMA, EMA, MACD, RSI, percentile rank; equals TA-Lib for EMA and RSI; 21 ms for 150 symbols × 260 rows |
| **TA-Lib 0.8.2** | 4.1 MB + numpy 16.7 MB | chosen; candle rules need gaps for morning star and piercing line |
| pandas 3.1.0 | 12.0 MB + numpy + python-dateutil | 78 ms; its RSI seeds with the first value, differs from Wilder's SMA seed by about 1e-8 |
| polars 2.1.0 | about 55 MB (runtime package 53.9 MB) | 1.7 ms, vectorisable half of the work only |
| pandas-ta 0.4.71b0 | very large | beta; pins `numba==0.61.2`, which forces numpy < 2.3 and pulls llvmlite |
| ta 0.11.0 | not installed | last release 2023-11-02, sdist only |

Speed does not matter at this size (all are far below one second against a 20-minute job); the differences are dependency weight, correctness conventions and code size.

### Gates and exclusions

| Gate | Rule |
|---|---|
| Liquidity | Step 2 already dropped symbols below 20 billion VND turnover. |
| Coverage | Compute a score only when the **available points ≥ 80**; show the coverage next to the score. Otherwise the symbol is `"insufficient data"` with no number, so a symbol with two days of data cannot reach 100 on a few cheap indicators. |
| Uptrend (#22, #23) | Counted only when **SMA50 is not falling** (the raw value of #4 is ≥ 0), i.e. a pullback inside an uptrend. Gate closed: 0 points but the indicator is still *available*. Gate input missing (too few rows): the indicator is *unavailable*. Without this gate, reversal points reward falling symbols that the trend items score low, and the two cancel out. |
| Missing session | A symbol whose fetch failed on some day has a gap in the history, so N rows cover more than N sessions, and two ceiling days around the gap look like one +14.5% jump. Build the **market calendar** from the distinct dates in the history artifact; run the band check only between *adjacent market sessions*; any fixed-window indicator whose window contains a market session missing for that symbol is *unavailable*; EMA / Wilder-based ones simply continue across the gap (skipping one row costs little). |
| Corporate action | A one-day change beyond the HOSE band (±7% to be verified; a symbol's first trading day after `listed_date` in `data/hose_symbols.csv` uses ±20%) marks the symbol "suspected corporate action". Any indicator whose window contains the jump is *unavailable*: fixed windows (SMAs, highs, returns, volume averages) exactly; EMA / Wilder-based ones (#8–#11, #22) are restarted from the first session after the jump and become available again once the rows since the jump reach their normal minimum rows, because their memory fades instead of ending; #23 when its 3 candles or its 5-session context contain it; #24 when its 60-session window contains it. A fake drop would otherwise look like a big bearish candle followed by a "reversal". A jump within the last 20 sessions removes most indicators, so the symbol becomes `"insufficient data"` until the history is refreshed. |

Flags, shown next to the score and **not** changing it: close within 0.5% of the ceiling (+7%, "locked, hard to buy"), new listing, suspected corporate action, low coverage.

### Output per symbol

`score` (null when the coverage gate fails), `coverage` (available points), theme subtotals, and for each indicator `id`, `points`, `max`, raw values, and `status` (`scored`, `gate_closed` or `unavailable`), plus the flags. Sort by score, ties by turnover. Phase 2 and the tests need the raw values, so the ranking is never a black box.

### Minimum history (computed from the table above)

| Rows in the history | Points available |
|---|---|
| 60 or fewer | at most 78 (not scored) |
| **61–69** | **82 (first scored row count)** |
| 70 | 92 |
| 200 | 98 |
| 250 or more | 100 |

The floor is 61 rows with a margin of 2 points. Any new indicator with a longer lookback moves the floor up by about 10 rows. Step 3 asks for 260 sessions so every indicator is available.

### Behaviour to expect

- Nobody reaches 100: the 10 reversal points and the breakout items rarely fire together. A breakout leader tops out at 90 and a pullback setup much lower, so the listing threshold (e.g. ≥ 60) must come from the real score distribution.
- Stacking: one event can fire several related items (MACD rising + cross + divergence + candle ≈ 15 points at a pullback bottom; trendline breakout + 20-session high + volume + MACD cross at a breakout). Accepted for now.
- The weights are a hypothesis. Once history exists, check them by score decile against the 5- and 20-session forward returns (not part of Phase 1).
- Candle patterns have low reliability, hence only 5 points.

## Simplification suggestions (ponytail review, none applied)

From a `/ponytail-review` of these plans on 2026-10-28. The agent that reads this document decides which to apply. Rough saving: about 400 lines of code and yaml that are not written yet (about 250 of them only deferred).

1. **Merge `vn_stock_get_history` into `vn_stock_screen`** (steps 2 and 3): same database, same session, so one runner and one artifact hop less and about 35 lines of yaml; `vn_stock_analyze` still gets no database secret. The user designed four jobs, so this is the user's call.
2. **Defer `market.json`** (breadth, median change) to Phase 2: no indicator uses it any more.
3. **Volume-definition check** (step 2): compare one liquid symbol across the three sources once by hand, instead of keeping it as a checklist item that implies shipped code.
4. **Stage #22–#24 after #1–#21**: 14 points but the heaviest code (pivots, four candle patterns, the trendline search) and the least reliable ones per this document. Caveat: the coverage gate is written against the full 100 points; with #22–#24 unimplemented nobody would reach 80 available points before 200 rows, so the gate would have to be computed against the implemented points (e.g. available ≥ 80% of implemented).
5. **Move `connect()`** (10 s connect and 60 s statement timeouts) from `scripts/vn_stock_daily_price_store.py` to `libs/db/__init__.py` next to `database_url()`, because steps 2 and 3 need it. Do not copy it or import from a script module.
6. **Step 3 output:** write JSON with `Price.model_dump(mode="json")` and read it back with the existing `read_prices` (it validates and drops duplicates); no new reader.
7. **Document hygiene:** move "Facts for the backfill task" to that task's own plan; delete Phase 2's "After Phase 2" paragraph; Phase 2's ticker check with the `VND` exception (about 10 lines) guards a failure the score table already exposes, so add it only when the LLM actually invents a ticker.
8. **Dropped:** the `session_date` job output; the session is simply today (VN).

## Notes

### Adjusted prices skew the history

All 3 sources return **adjusted** prices (`vndirect.py` reads the `ad*` fields to match DNSE and VPS). Adjusted past prices change whenever a new corporate action happens, while a row already stored in `prices` keeps the value it had when stored. On an ex-rights day, today's `close` compared with the stored previous `close` gives a fake drop, and it pollutes every moving average, high and return whose window contains that day. Phase 1 does not refresh stored history, so `vn_stock_analyze` must detect it (step 4); the real fix is to re-fetch the history of the shortlist periodically, which belongs to the backfill task.

### Known limits

- A cash dividend smaller than the price band cannot be told apart from a real drop without an events calendar; it stays in the data.
- To verify: whether a stock's first session after a long trading suspension also gets a wider band, like a new listing. If so, the corporate-action check needs the same exception.

### Facts for the backfill task (not Phase 1)

- `dnse.py` and `vps.py` already call a history endpoint with a `from/to` window (10 days, keeping only `[-1]`); `vndirect.py` calls with `size=1`. So `get_history` is mostly a parameter change.
- DNSE and VPS count calendar days, VNDirect counts sessions: define the parameter as sessions and trim.
- VNDirect answers `sort=date:desc`: `get_history` must return ascending dates, and `get_latest_price` must stay the row with the max date (test it per source).
- The volume-definition check is already in step 2; it matters for any history the backfill writes too.

### Open questions

1. How to compute in `vn_stock_analyze`: SQL window functions, or plain Python on the history artifact?
2. Weights and thresholds: tune them after seeing the real score distribution. Also decide whether to add the hidden bullish divergence, and where to set the listing threshold.
3. History length N for step 3: 260 recommended (see Minimum history).
4. Who fills the history in `prices`, and when (the Assumption above)?
5. Candle patterns with TA-Lib: hand-write the gap-free morning star and piercing line, or accept TA-Lib's gap-based ones?
6. Which of the ponytail suggestions to apply?
