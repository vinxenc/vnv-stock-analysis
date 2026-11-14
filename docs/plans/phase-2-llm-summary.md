# Phase 2 — One LLM call to summarize

Status: **draft, not started** (2026-11-14; first draft 2026-10-28). Comes after [phase-1-sql-screens.md](phase-1-sql-screens.md), which has run green on GitHub since 2026-11-11. Work through the checklist below in order: one step = one PR.

## Goal

Turn `out/vn_stock_analysis.json` (the Phase 1 output) into a **pre-market HOSE summary of the previous session** with exactly one Claude API call. No agent loop, no tools.

## Prerequisites

- [x] Phase 1 has run reliably for a few days; the score table is correct and readable. Met on 2026-11-14: green runs on 11-11, 11-12 and 11-13; the one cron failure (11-12) was GitHub starting the run after midnight VN with no bar yet for the session due, a false alarm.
- [ ] The delivery channel is settled. Default: GitHub job summary; another channel is decided in step 6.

## Decisions and open items

Decided (review of 2026-11-14, against the code on `master`):
- **Compact input, not the full JSON.** One `SymbolResult` with its 24 `indicators` is about 3.2 KB even with a minimal `raw` (measured on a synthetic row); about 100 shortlisted symbols is over 300 KB, roughly 100k tokens a day. Without `indicators` a symbol is about 0.2 KB. The call gets market numbers plus the top N symbols with score, coverage, theme points, flags and only their 3 biggest indicators (step 2).
- **Market numbers are computed in `vn_stock_analyze`**, not in `vn_stock_screen`. The first draft put them in the screen because only it had the database; since 2026-11-11 `vn_stock_analyze` has `DATABASE_URL` (it upserts `vn_stock_rankings`). No `market.json`, no second artifact download, no `needs` change (step 1).
- **`vn_stock_summary` is a leaf job.** `needs: vn_stock_analyze`; only `notification` needs it, **not** `vn_stock_screen_done`: otherwise an API outage leaves the session due and the next run redoes the whole analysis (step 5).
- **The ticker check ignores indicator names.** `VND`, `SMA` and `CCI` are HOSE tickers (`data/hose_symbols.csv`); the ignore list is `{"VND"}` plus the indicator names of `libs/analysis`, guarded by a test (step 3).
- The job needs only `ANTHROPIC_API_KEY` (`production` environment), **no** `DATABASE_URL`; the `vn-stock-analysis` artifact sits between the two jobs.

Open questions (each blocks the step named):
1. Summary language: Vietnamese? (step 3)
2. Daily cost ceiling? (step 6, from the logged token counts)
3. `anthropic` SDK (retries and errors built in, the default) or the installed `niquests` (one dependency fewer)? (step 4)
4. Another delivery channel (Telegram, email, a DB table)? (step 6)

## Checklist

### 1. Market-wide numbers in the analysis JSON (no LLM)

A pre-market summary needs the state of the whole market, not only the shortlist; Phase 1 left it out (no indicator uses it).

- [ ] Two SQL aggregates over `vn_stock_prices` for the session `as_of` (the session screened, which may be before the real today; never the wall-clock day), each reported with its symbol count:
  - Volume and estimated turnover (`close × volume`, thousand VND; the table has no traded value, so it is an estimate), over **every** symbol with a row on that session, so a new listing is included.
  - Advancers / decliners / unchanged and the median one-day change, only over symbols with a row on that session **and** the preceding one (a change needs both).
- [ ] New field `market` in `AnalysisReport` (`libs/analysis/models.py`). The model forbids extra fields, so this is a deliberate contract change: say so in its docstring.
- [ ] `vn_stock_analyze` fills it after reading the history and before writing the JSON. A database error fails the job like any other.
- [ ] `libs/analysis/summary.py` prints a "Market" block above the score table, so the step is useful without any LLM.
- [ ] Wording: the scope is the symbols of `data/hose_symbols.csv`, so "HOSE", not "the whole market". An ex-rights day (adjusted close against the stored previous close, see Phase 1 Notes) shifts the advancer / decliner counts slightly; the median absorbs it.
- [ ] Tests on the real Postgres fixture: a new listing, a symbol missing on the previous session, an ex-rights day, no previous session.
- [ ] Done when: a local run with `DATABASE_URL` prints the block and `out/vn_stock_analysis.json` carries `market`.

### 2. Compact input for the LLM (pure function, no network)

- [ ] `libs/analysis/llm_input.py`: `build_input(report, top_n)` → a pydantic model. Content: `as_of`, `market`, shortlist coverage, the counts of scored and insufficient-data symbols, and for the top `top_n`: score, coverage, theme points, flags, the 3 biggest indicators by points with `raw`.
- [ ] `top_n` is one constant, 20 to start; the final number comes from step 6.
- [ ] Symbols with no score appear only in the counts, never with a number.
- [ ] An `unavailable` indicator is never picked as one of the 3.
- [ ] A test pins the size: a realistic report of about 100 symbols serialises under a set limit (for example 30 KB), so nobody grows the input by accident.
- [ ] Done when: the output for a real `vn_stock_analysis.json` fits on one screen and is under the limit.

### 3. Prompt and post-call check (pure functions, no network)

- [ ] `libs/analysis/llm_prompt.py`: `build_prompt(input)` → `(system, user)`. Rules for the model:
  - [ ] Language: Vietnamese, unless open question 1 says otherwise.
  - [ ] Describe only the data given; do not invent numbers; no buy/sell recommendations; end with a one-line "for reference only".
  - [ ] May quote the 0–100 score, its points, raw values and flags, but must not present the score as a recommendation; must show a flag (ceiling-locked, new listing, low coverage) next to any symbol that has one.
  - [ ] A symbol with insufficient data has no score and is never given one; an `unavailable` indicator is reported as such, never guessed.
  - [ ] Write the currency as "đồng", **not** "VND".
  - The input is numbers and symbols only, no free text, so the prompt-injection risk is low.
- [ ] `check_symbols(summary, allowed, known, ignore)` → the unknown symbols (empty = pass):
  - [ ] Take the uppercase words of the summary that **are in `data/hose_symbols.csv`** and compare them with the symbols of the input. No "3 uppercase letters" regex (it would flag RSI, ETF, USD, …).
  - [ ] `ignore` = `{"VND"}` (the currency; VNDirect is line 383 of the CSV) plus the indicator names `libs/analysis` uses.
  - [ ] A test loads the CSV and fails if an indicator name is a ticker missing from `ignore` (today `SMA` and `CCI`).
- [ ] Tests: an invented symbol is caught; "VND" as money and "SMA20" pass.
- [ ] Done when: both functions are covered by unit tests, with no network and no secret.

### 4. `scripts/vn_stock_summary.py` and the API call

- [ ] Answer open questions 1 and 3; pick the model and parameters from the current API docs (the `claude-api` skill).
- [ ] The script: read the JSON → `build_input` → `build_prompt` → one call → `check_symbols` → write `out/vn_stock_summary.md` and `$GITHUB_STEP_SUMMARY` (the log when unset).
- [ ] The call is a small function that takes the client, so the tests mock it (95% coverage gate).
- [ ] API error → exit non-zero, nothing written. Unknown symbols → exit non-zero with the list. The Phase 1 table is already in the job summary either way (written by `vn_stock_analyze`).
- [ ] Log through `Logger`, including the input and output token counts (the cost per run).
- [ ] Tests with a mocked client: success, API error, invented symbol, empty analysis.
- [ ] **Manual run** on this machine with a real `out/vn_stock_analysis.json` and the user's key (in the shell only, never in a file): read the summary, adjust the prompt. The only step that costs money.
- [ ] Done when: the manual run gives a summary a person would use, and the token count matches "a few thousand input tokens, one call a day".

### 5. Workflow job and pipeline wiring

- [ ] Job `vn_stock_summary` in `.github/workflows/vn-stock-analysis.yml`: `needs: vn_stock_analyze`, `environment: production`, secret `ANTHROPIC_API_KEY`, no `DATABASE_URL`, downloads the `vn-stock-analysis` artifact. Same boilerplate as the other jobs (pinned actions, `setup-env`, timeout).
- [ ] Ends with the `pipeline-state` action; add it to `notification`'s `needs`.
- [ ] **Not** in `vn_stock_screen_done`'s `needs`.
- [ ] The user adds `ANTHROPIC_API_KEY` to the `production` environment (the value never passes through Claude).
- [ ] README: files table and job list.
- [ ] Done when: a real `workflow_dispatch` run shows the score table (Phase 1) and the summary (Phase 2) in the job summary; a run with a wrong key fails only `vn_stock_summary`, the table is still shown and the session is still recorded.

### 6. Watch it for a few days, then decide the rest

- [ ] A few scheduled runs: read each summary; count the runs where the symbol check failed or a figure disagrees with the table.
- [ ] Tune the prompt and `top_n`; set the cost ceiling (open question 2).
- [ ] Decide open question 4 (delivery channel) with real summaries in hand.
- [ ] Done when: a few days without a wrong figure, `uv run pytest` ≥ 95% coverage, ruff clean; this plan's status becomes "built".

## After Phase 2 (not planned yet)

An agent with a read-only SQL tool (option 2) is only worth building if the fixed SQL screens cannot answer your questions. It would need: a Postgres role with SELECT on `vn_stock_prices` only and its own secret, a `READ ONLY` transaction with a timeout and a row limit, limits on turns and tokens, and a set of golden questions for evaluation. Write a separate plan then.
