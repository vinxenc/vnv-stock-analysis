# Phase 2 — LLM assessment of each symbol

Status: **draft, not started** (2026-11-14; first draft 2026-10-28). Comes after [phase-1-sql-screens.md](phase-1-sql-screens.md), which has run green on GitHub since 2026-11-11. Work through the checklist below in order: one step = one PR.

## Goal

For each of the top N symbols of the Phase 1 ranking, **one Claude API call reads that symbol's result alone** (its score, theme points, indicators with raw values, flags) and writes a short assessment of it. Each symbol is judged independently: no market overview, no comparison between symbols, no agent loop, no tools.

## Prerequisites

- [x] Phase 1 has run reliably for a few days; the score table is correct and readable. Met on 2026-11-14: green runs on 11-11, 11-12 and 11-13; the one cron failure (11-12) was GitHub starting the run after midnight VN with no bar yet for the session due, a false alarm.

## Decisions and open items

Decided (2026-11-14):
- **Per symbol, not one summary.** The call's input is one `SymbolResult` from `out/vn_stock_analysis.json` as it is (about 3 KB, roughly a thousand tokens), so nothing has to be shortened.
- **No market-wide numbers** (breadth, total turnover, median change): not needed to judge one symbol. Phase 1 deferred them to this phase; they are dropped, not planned anywhere now.
- **Only the top N scored symbols**, `N` one constant (start with 20): a symbol without a score or with 0 points is not sent.
- **No ticker check after the call.** Each input holds a single symbol, so mixing symbols up is unlikely, and the Phase 1 table is next to the text anyway. Revisit only if step 4 shows the model naming other tickers.
- **Leaf job.** `vn_stock_summary` has `needs: vn_stock_analyze`; only `notification` needs it, **not** `vn_stock_screen_done`: otherwise an API outage leaves the session due and the next run redoes the whole analysis.
- The job needs only `ANTHROPIC_API_KEY` (`production` environment), **no** `DATABASE_URL`; the `vn-stock-analysis` artifact sits between the two jobs.

Open questions (each blocks the step named):
1. Assessment language: Vietnamese? (step 1)
2. `anthropic` SDK (retries and errors built in, the default) or the installed `niquests` (one dependency fewer)? (step 2)
3. `N` and a daily cost ceiling? (step 4, from the logged token counts)
4. Another delivery channel (Telegram, email, a DB table)? (step 4)

## Checklist

### 1. Prompt (pure function, no network)

- [ ] `libs/analysis/llm_prompt.py`: `build_prompt(as_of, symbol_result)` → `(system, user)`; the user message is the `SymbolResult` JSON plus the session date. Rules for the model:
  - [ ] Language: Vietnamese, unless open question 1 says otherwise.
  - [ ] Judge only this symbol from the data given: which themes carry the score, which indicators stand out, what the flags warn about. A few sentences.
  - [ ] Do not invent numbers or facts (news, financials, other symbols); no buy/sell recommendation; end with a one-line "for reference only".
  - [ ] Show any flag (ceiling-locked, new listing, low coverage); an `unavailable` indicator is reported as such, never guessed.
  - The input is numbers and fixed names only, no free text, so the prompt-injection risk is low.
- [ ] `select_symbols(report, n)`: the first `n` symbols of the ranking with a score above 0 (the report is already sorted).
- [ ] Tests: the prompt carries the symbol's data and the session; `select_symbols` skips null and 0 scores and stops at `n`.
- [ ] Done when: both functions are covered by unit tests, with no network and no secret.

### 2. `scripts/vn_stock_summary.py` and the API call

- [ ] Answer open questions 1 and 2; pick the model and parameters from the current API docs (the `claude-api` skill).
- [ ] The script: read the JSON → `select_symbols` → for each symbol, one call → write `out/vn_stock_summary.md` (one section per symbol, in ranking order) and `$GITHUB_STEP_SUMMARY` (the log when unset).
- [ ] The call is a small function that takes the client, so the tests mock it (95% coverage gate).
- [ ] One failed call does not stop the others: that symbol's section says it failed, and the script exits non-zero at the end. The Phase 1 table is already in the job summary either way (written by `vn_stock_analyze`).
- [ ] Log through `Logger`, including the total input and output token counts (the cost per run).
- [ ] Tests with a mocked client: all succeed, one API error among several, no symbol to assess.
- [ ] **Manual run** on this machine with a real `out/vn_stock_analysis.json` and the user's key (in the shell only, never in a file): read the assessments, adjust the prompt. The only step that costs money before step 3.
- [ ] Done when: the manual run gives assessments a person would use, and the token counts are logged.

### 3. Workflow job and pipeline wiring

- [ ] Job `vn_stock_summary` in `.github/workflows/vn-stock-analysis.yml`: `needs: vn_stock_analyze`, `environment: production`, secret `ANTHROPIC_API_KEY`, no `DATABASE_URL`, downloads the `vn-stock-analysis` artifact. Same boilerplate as the other jobs (pinned actions, `setup-env`, timeout).
- [ ] Ends with the `pipeline-state` action; add it to `notification`'s `needs`.
- [ ] **Not** in `vn_stock_screen_done`'s `needs`.
- [ ] The user adds `ANTHROPIC_API_KEY` to the `production` environment (the value never passes through Claude).
- [ ] README: files table and job list.
- [ ] Done when: a real `workflow_dispatch` run shows the score table (Phase 1) and the assessments (Phase 2) in the job summary; a run with a wrong key fails only `vn_stock_summary`, the table is still shown and the session is still recorded.

### 4. Watch it for a few days, then decide the rest

- [ ] A few scheduled runs: read the assessments; note any figure that disagrees with the table or any invented fact.
- [ ] Tune the prompt; set `N` and the cost ceiling (open question 3).
- [ ] Decide open question 4 (delivery channel) with real assessments in hand.
- [ ] Done when: a few days without a wrong figure, `uv run pytest` ≥ 95% coverage, ruff clean; this plan's status becomes "built".

## After Phase 2 (not planned yet)

An agent with a read-only SQL tool is only worth building if the fixed screens cannot answer your questions. It would need: a Postgres role with SELECT on `vn_stock_prices` only and its own secret, a `READ ONLY` transaction with a timeout and a row limit, limits on turns and tokens, and a set of golden questions for evaluation. Write a separate plan then.
