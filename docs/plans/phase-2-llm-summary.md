# Phase 2 — One LLM call to summarize

Status: **draft, not started** (2026-10-28). Comes after [phase-1-sql-screens.md](phase-1-sql-screens.md).

## Goal

Turn `out/vn_stock_analysis.json` (the Phase 1 output) into a **pre-market HOSE summary of the previous session** with exactly one Claude API call. No agent loop, no tools.

## Prerequisites

- Phase 1 has run reliably for a few days; the score table is correct and readable.
- The delivery channel is settled (default: GitHub job summary).

## Design

- Job `vn_stock_summary`, `needs: vn_stock_analyze`. It only needs the secret `ANTHROPIC_API_KEY` (`production` environment) and **no** `DATABASE_URL`. The `vn-stock-analysis` artifact sits between the two jobs, the same way `retrieve_prices` → `store` works today.
- Script `scripts/vn_stock_summary.py`: JSON → LLM → `out/vn_stock_summary.md`, also written to `$GITHUB_STEP_SUMMARY`.
- The API call goes in a small function that takes the client, so tests can mock it (95% coverage gate).
- Model, `anthropic` SDK vs the already-installed `niquests`, parameters: **decide when building**, after reading the current API docs.
- Cost: a short list (a few dozen rows) → a few thousand input tokens per day, one call.

## Prompt

- Summary language: Vietnamese (to be confirmed).
- Describe only the data given; do not invent numbers; no buy/sell recommendations; end with a one-line "for reference only".
- The input carries a 0–100 screening score per symbol with per-indicator points, raw values and flags. The summary may quote them, must not present the score as a recommendation, and must show a flag (ceiling-locked, suspected corporate action, new listing) next to any symbol that has one.
- A symbol marked `"insufficient data"` has no score and must not be given one; an `unavailable` indicator is reported as such, never guessed.
- Write the currency as "đồng", **not** "VND" (see the check below).
- The input is numbers and symbols only, no free text, so the prompt-injection risk is low.

## Post-call check (cheap)

Every symbol in the summary must appear in the input JSON; otherwise fail the job (the Phase 1 score table is still there).

- Take the uppercase words in the summary that **are in `data/hose_symbols.csv`**, and compare them with the set of symbols in the JSON.
- Do not use a "3 uppercase letters" regex: it would wrongly flag RSI, ETF, USD, and so on.
- **`VND` is both the currency and a HOSE ticker** (VNDirect, line 383 of the CSV): the check would wrongly fail if the summary writes "VND" as money. The prompt says to write "đồng"; add an ignore list `{"VND"}` in case it slips through.

## Pipeline integration

- End the job with the `pipeline-state` action; add it to `notification`'s `needs`.
- Log through `Logger`.

## Definition of done

- A real `workflow_dispatch` run → the job summary has the score table (Phase 1) and the summary (Phase 2).
- A summary that contains a symbol not in the JSON (mocked) → the job fails with a clear message.
- API error → the job fails, the Phase 1 score table is still shown.
- `uv run pytest` ≥ 95% coverage, ruff clean.

## Open questions

1. Summary language: Vietnamese?
2. Daily cost ceiling?
3. `anthropic` SDK (retries and errors built in) or the installed `niquests` (one dependency fewer)?
4. Another delivery channel (Telegram, email, a DB table)?

## After Phase 2 (not planned yet)

An agent with a read-only SQL tool (option 2) is only worth building if the fixed SQL screens cannot answer your questions. It would need: a Postgres role with SELECT on `prices` only and its own secret, a `READ ONLY` transaction with a timeout and a row limit, limits on turns and tokens, and a set of golden questions for evaluation. Write a separate plan then.
