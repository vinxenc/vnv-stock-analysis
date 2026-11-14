# Phase 2 — One LLM call to summarize

Status: **draft, split into 6 steps, not started** (2026-11-14; first draft 2026-10-28). Comes after [phase-1-sql-screens.md](phase-1-sql-screens.md), which has run green on GitHub since 2026-11-11.

## Goal

Turn `out/vn_stock_analysis.json` (the Phase 1 output) into a **pre-market HOSE summary of the previous session** with exactly one Claude API call. No agent loop, no tools.

## Prerequisites

- Phase 1 has run reliably for a few days; the score table is correct and readable. (Met on 2026-11-14: green runs on 11-11, 11-12 and 11-13; the one cron failure, 11-12, was GitHub starting the run after midnight VN with no bar yet for the new session due, a false alarm.)
- The delivery channel is settled (default: GitHub job summary).

## Review findings (2026-11-14), what changed in this plan

1. **The JSON is far too big to send as it is.** The plan said "a few dozen rows, a few thousand tokens". One `SymbolResult` with its 24 `indicators` is about 3.2 KB even with a minimal `raw` (measured on a synthetic row); about 100 shortlisted symbols is over 300 KB, roughly 100k tokens, every day. Without `indicators` a symbol is about 0.2 KB (about 20 KB for 100, a few thousand tokens). So the call gets a **compact input** (step 2): market numbers, the top N symbols with score, coverage, theme points and flags, and for each only its 3 biggest indicators with their raw values.
2. **Market numbers: compute them in `vn_stock_analyze`, not in `vn_stock_screen`.** The old reason for the screen was that only it had the database. Since 2026-11-11 `vn_stock_analyze` has `DATABASE_URL` (it upserts `vn_stock_rankings`), so it can run the two aggregates itself. That drops `market.json`, the second artifact download and the `needs: vn_stock_screen` change. The session is the report's `as_of` (the session screened, which may be before the real today), never the wall-clock day.
3. **`vn_stock_summary` must not block `vn_stock_screen_done`.** That job records the session only after the analysis succeeded. If it also waited for the summary, an API outage would leave the session due and the next run would redo the whole analysis. The summary is a leaf job: `needs: vn_stock_analyze`, nobody `needs` it except `notification`.
4. **The ticker check collides with indicator names.** Besides `VND`, `SMA` and `CCI` are HOSE tickers (checked in `data/hose_symbols.csv`), and the summary will write "SMA20" style words. The ignore list is built from the indicator names `libs/analysis` uses, plus `VND`, not a hand-kept list; a test fails when a new indicator name collides with a ticker that is not ignored.
5. Cosmetic: the plan said the `prices` table; it is `vn_stock_prices` since migration `0007`. Phase 2 reads no table, so only the closing note changes.

## Steps

Each step is one PR, mergeable and tested on its own. Only step 4 touches the API and only step 5 touches the workflow, so steps 1–3 cost nothing and risk nothing in production.

### Step 1. Market-wide numbers in the analysis JSON (no LLM)

- [ ] `libs/analysis` (or a small module next to `vn_stock_analyze`): two SQL aggregates over `vn_stock_prices` for the session `as_of`, see "Market-wide numbers" below.
- [ ] A new field `market` in `AnalysisReport` (`libs/analysis/models.py`): symbol counts, advancers / decliners / unchanged, median one-day change, volume, estimated turnover. The model forbids extra fields, so adding it is a deliberate contract change: say so in its docstring.
- [ ] `vn_stock_analyze` fills it, after the history is read and before the JSON is written. A database error here fails the job like any other (the job already needs the database).
- [ ] The job summary (`libs/analysis/summary.py`) prints a "Market" block above the score table, so step 1 is useful without any LLM.
- [ ] Tests on the real Postgres fixture: a new listing, a symbol missing on the previous session, an ex-rights day, an empty previous session.
- Done when: a local run (`DATABASE_URL` set) prints the block and `out/vn_stock_analysis.json` carries `market`.

### Step 2. Compact input for the LLM (pure function, no network)

- [ ] `libs/analysis/llm_input.py`: `build_input(report, top_n) -> dict` (or a pydantic model). Content: `as_of`, `market`, shortlist coverage, the counts of scored / insufficient-data symbols, and for the top `top_n` symbols: score, coverage, theme points, flags and their 3 biggest indicators by points with `raw`.
- [ ] `top_n` is one constant (start with 20; decide the final number from the size in the next bullet and the readability of the summary in step 6).
- [ ] A test pins the size: for a realistic report of about 100 symbols the serialised input stays under a set limit (for example 30 KB), so nobody grows the input by accident.
- [ ] Symbols with no score are never listed with a number; they appear only in the counts.
- Done when: the function output for a real `vn_stock_analysis.json` can be read by a person in one screen and is under the limit.

### Step 3. Prompt and post-call check (pure functions, no network)

- [ ] `libs/analysis/llm_prompt.py`: `build_prompt(input) -> (system, user)` following "Prompt" below. Language is an open question (1); until it is answered the prompt is written for Vietnamese.
- [ ] `check_symbols(summary, allowed, known_symbols, ignore) -> list[str]`: the uppercase words that are HOSE tickers (`data/hose_symbols.csv`), are not in `ignore` and are not in the input. Empty list = pass.
- [ ] `ignore` = `{"VND"}` plus the indicator names `libs/analysis` uses; a test loads the CSV and fails if an indicator name is a ticker and is missing from `ignore` (today `SMA` and `CCI`).
- [ ] Tests: a summary that invents a symbol is caught; "VND" as money and "SMA20" pass; a flagged symbol must show its flag (cheap string check, optional).
- Done when: both functions are covered by unit tests, no network and no secret needed.

### Step 4. `scripts/vn_stock_summary.py` and the API call

- [ ] Resolve open questions 1 and 3 first (language, `anthropic` SDK or `niquests`); choose the model and parameters from the current API docs (the `claude-api` skill).
- [ ] The script: read the JSON → `build_input` → `build_prompt` → one call → `check_symbols` → write `out/vn_stock_summary.md` and `$GITHUB_STEP_SUMMARY` (the log when it is unset). The call is a small function that takes the client, so the tests mock it.
- [ ] Failures: API error → exit non-zero, nothing written; symbol check fails → exit non-zero with the list of unknown symbols; the Phase 1 score table is already in the job summary either way (written by `vn_stock_analyze`).
- [ ] Log through `Logger`; log the input and output token counts, so the cost is visible per run.
- [ ] Tests with a mocked client: success, API error, invented symbol, empty analysis.
- [ ] **Manual run** on this machine against a real `out/vn_stock_analysis.json` with a real key (the user's, in the shell only, never in a file): read the summary, adjust the prompt. This is the only step that costs money.
- Done when: the manual run produces a summary a person would use, and the token count matches the cost estimate.

### Step 5. Workflow job and pipeline wiring

- [ ] Job `vn_stock_summary` in `.github/workflows/vn-stock-analysis.yml`: `needs: vn_stock_analyze`, `environment: production`, secret `ANTHROPIC_API_KEY`, **no** `DATABASE_URL`, downloads the `vn-stock-analysis` artifact, runs the script. Same boilerplate as the other jobs (pinned actions, `uv` cache, timeout).
- [ ] Ends with the `pipeline-state` action; add the job to `notification`'s `needs`.
- [ ] Do **not** add it to `vn_stock_screen_done`'s `needs` (finding 3).
- [ ] Add the secret to the `production` environment (the user does it; I never see the value).
- [ ] README: files table and the job list.
- Done when: a real `workflow_dispatch` run → the job summary has the score table (Phase 1) and the summary (Phase 2); a run with a wrong key fails only `vn_stock_summary`, the session is still recorded and the table still shown.

### Step 6. Watch it for a few days, then decide the rest

- [ ] A few scheduled runs: read each summary, count the runs where the symbol check failed or a figure was wrong against the table.
- [ ] Fix the prompt, `top_n` and the cost ceiling (open question 2) from what the runs show.
- [ ] Decide open question 4 (another delivery channel) only now, with real summaries in hand.
- Done when: a few days pass without a wrong figure, then this plan's status becomes "built".

## Design

- Job `vn_stock_summary`, `needs: vn_stock_analyze`. It only needs the secret `ANTHROPIC_API_KEY` (`production` environment) and **no** `DATABASE_URL`. The `vn-stock-analysis` artifact sits between the two jobs, the same way `retrieve_prices` → `store` works today.
- Script `scripts/vn_stock_summary.py`: JSON → LLM → `out/vn_stock_summary.md`, also written to `$GITHUB_STEP_SUMMARY`.
- The API call goes in a small function that takes the client, so tests can mock it (95% coverage gate).
- Model, `anthropic` SDK vs the already-installed `niquests`, parameters: **decide when building** (step 4), after reading the current API docs.
- Cost: one call a day. The input is the compact one of step 2 (a few thousand tokens), not the full JSON (see finding 1). Log the token counts to confirm.

## Market-wide numbers (deferred from Phase 1; step 1)

A pre-market summary needs the state of the whole market, not only the shortlist. Phase 1 left it out (no indicator uses it). Add it here:

- Two scopes, both reported with their symbol counts, both for the session `as_of`:
  - Volume and estimated turnover (`close × volume`, thousand VND; the table has no traded value, so it is an estimate): summed over **every** symbol with a row on that session, so a new listing is included.
  - Advancers / decliners / unchanged and the median one-day change: only over symbols with a row on that session **and** the preceding one (a change needs both). The summary says how many symbols that is out of the session's total.
  - One SQL aggregate for each scope.
- Computed in `vn_stock_analyze` and stored in `AnalysisReport.market` (finding 2). The summary job still reads only the analysis JSON, so Phase 1's output contract stays the single input of Phase 2.
- Caveats: the scope is the symbols in `data/hose_symbols.csv`, so say "HOSE", not "the whole market". Today's adjusted close against the stored previous close skews symbols with an ex-rights day (see Phase 1 Notes); the median absorbs it, the advancer / decliner counts shift slightly.
- Tests on the real Postgres fixture, like the screen's.

## Prompt

- Summary language: Vietnamese (to be confirmed).
- Describe only the data given; do not invent numbers; no buy/sell recommendations; end with a one-line "for reference only".
- The input carries a 0–100 screening score per symbol with per-indicator points, raw values and flags. The summary may quote them, must not present the score as a recommendation, and must show a flag (ceiling-locked, new listing, low coverage) next to any symbol that has one.
- A symbol marked `"insufficient data"` has no score and must not be given one; an `unavailable` indicator is reported as such, never guessed.
- Write the currency as "đồng", **not** "VND" (see the check below).
- The input is numbers and symbols only, no free text, so the prompt-injection risk is low.

## Post-call check (cheap; step 3)

Every symbol in the summary must appear in the input JSON; otherwise fail the job (the Phase 1 score table is still there).

- Take the uppercase words in the summary that **are in `data/hose_symbols.csv`**, and compare them with the set of symbols in the input.
- Do not use a "3 uppercase letters" regex: it would wrongly flag RSI, ETF, USD, and so on.
- **`VND` is both the currency and a HOSE ticker** (VNDirect, line 383 of the CSV), and so are `SMA` and `CCI` (indicator names): the check would wrongly fail. The prompt says to write "đồng"; the ignore list is `{"VND"}` plus the indicator names (finding 4).

## Pipeline integration (step 5)

- End the job with the `pipeline-state` action; add it to `notification`'s `needs`.
- Not in `vn_stock_screen_done`'s `needs`.
- Log through `Logger`.

## Definition of done

- A real `workflow_dispatch` run → the job summary has the score table (Phase 1) and the summary (Phase 2).
- A summary that contains a symbol not in the JSON (mocked) → the job fails with a clear message.
- API error → the job fails, the Phase 1 score table is still shown, and the session is still recorded.
- `uv run pytest` ≥ 95% coverage, ruff clean.

## Open questions

1. Summary language: Vietnamese? (blocks step 3's prompt text and step 4)
2. Daily cost ceiling? (decide in step 6 from the logged token counts)
3. `anthropic` SDK (retries and errors built in) or the installed `niquests` (one dependency fewer)? (decide in step 4; the SDK is the default)
4. Another delivery channel (Telegram, email, a DB table)? (step 6)

## After Phase 2 (not planned yet)

An agent with a read-only SQL tool (option 2) is only worth building if the fixed SQL screens cannot answer your questions. It would need: a Postgres role with SELECT on `vn_stock_prices` only and its own secret, a `READ ONLY` transaction with a timeout and a row limit, limits on turns and tokens, and a set of golden questions for evaluation. Write a separate plan then.
