# Phase 2 — Buy / skip decision per symbol (Claude and Jev)

Status: **draft, not started** (2026-11-14; first draft 2026-10-28 was a market summary, replaced). Comes after [phase-1-sql-screens.md](phase-1-sql-screens.md), which has run green on GitHub since 2026-11-11. Work through the checklist below in order: one step = one PR.

## Goal

For each of the top N symbols of the Phase 1 ranking, give **one symbol's data** to a model and get back **buy or skip, with a probability**. Two models answer side by side, Claude (LLM) and [Jev](https://openrouter.ai/blog/insights/what-is-jev/) (TypeSafe's decision model), and every answer is stored. Five sessions later the outcome is filled in, so each model's hit rate and calibration can be measured, and the setup (prompt, threshold, calibration, inputs) is adjusted from what is measured.

The decision is the system's output for the user to screen with; the user decides what to trade.

## Prerequisites

- [x] Phase 1 has run reliably for a few days (green runs on 2026-11-11, 12 and 13; the one cron failure, 11-12, was a false alarm: GitHub started the run after midnight VN).
- [ ] A TypeSafe (or reseller) account and API key for Jev, and an Anthropic API key: created by the user, never seen by Claude.

## Decisions and open items

Decided by the user (2026-11-14):
- **Per symbol, independent.** One call per symbol and model; no market overview, no comparison between symbols in one call.
- **Both models, side by side:** each symbol is sent to Claude and to Jev; both answers go into the same table. Cost: twice the calls.
- **A buy is right** when `close(t+5) ≥ close(t) × 1.03`: the close 5 sessions after the session decided (`t`) is at least 3% above the close of `t`. Sessions, not calendar days. A skip is right when that does not happen.
- **Input today:** that symbol's row of `vn_stock_rankings` (score, themes, indicators with raw values, flags) plus its last 60 sessions of `vn_stock_prices`. More sources later are more fields in the input, not a new design.
- **"Adjusted over time"** means what is around the models, since their weights cannot be trained on this data: a calibration map from stated probability to measured hit rate, the buy threshold, the prompt / question, and later the Phase 3 probability as one more input.

Decided while writing this plan (change if wrong):
- Only the top N scored symbols (score above 0), `N` one constant, 20 to start.
- The job reads and writes the database (`DATABASE_URL`), because both its inputs and its output are tables.
- Leaf job: `needs: vn_stock_analyze`; only `notification` needs it, **not** `vn_stock_screen_done`, so an API outage never leaves the session due.
- Known limits of the label: the decision is made after the close of `t`, so `close(t)` is not a price anyone could still buy at; the label is optimistic by one session's move. Adjusted prices skew an ex-rights week (Phase 1 Notes). A halted symbol with no bar at `t+5` keeps an empty outcome.

Open questions (each blocks the step named):
1. Jev endpoint: TypeSafe's own API or a reseller (OpenRouter, AI/ML API); the sources disagree on the URL. Read the official docs when building. (step 3)
2. Claude model and `anthropic` SDK vs `niquests` (SDK is the default). (step 3)
3. Reason language for Claude: Vietnamese? (step 3)
4. Daily cost ceiling and the final `N`. (step 7)

## Checklist

### 1. Table `vn_stock_decisions`

- [ ] Migration `0009`: table `vn_stock_decisions`, primary key (`date`, `symbol`, `model`). Columns: `decision` (`buy` / `skip`), `probability` (0–1, the probability of buy as the model states it), `reason` (text, null for Jev), `model_version`, `input` (JSONB: the exact input sent, so any answer can be re-read later), `created_at`, and the outcome: `return_5` (null until known) and `hit` (boolean, null until known).
- [ ] SQLModel class in `libs/db/models.py`; the migration names the table as a string (`CLAUDE.md`).
- [ ] Migration test like the existing ones; `alembic check` clean.
- [ ] Done when: `alembic upgrade head` on a fresh local database creates it.

### 2. Input per symbol (pure function plus one query, no API)

- [ ] `libs/decision/input.py`: `build_input(ranking_row, bars)` → one pydantic model: symbol, session `t`, score, coverage, themes, indicators (status, points, raw), flags, and the last 60 bars (date, open, high, low, close, volume).
- [ ] `load_candidates(engine, t, n)`: the top `n` rows of `vn_stock_rankings` for `t` (`score DESC, turnover DESC`) and their bars from `vn_stock_prices` up to `t`, never after (no look-ahead).
- [ ] Tests on the real Postgres fixture: order, `n`, no bar after `t`, a symbol with fewer than 60 bars.
- [ ] Done when: for a real session the input of one symbol is readable on one screen.

### 3. The two deciders (mocked in tests)

- [ ] One small interface `Decider` with `decide(input) -> Decision(decision, probability, reason, model_version)`, like `Indicators` in `libs/indicators`: one class per model, the client passed in, so tests mock it.
- [ ] `ClaudeDecider`: one call, structured JSON output `{decision, probability, reason}`; the prompt says to judge only from the data given, invent nothing (news, financials, other symbols), report an `unavailable` indicator as such, and states the target (+3% in 5 sessions) so the probability means that.
- [ ] `JevDecider`: the same input as state, one typed question "will the close 5 sessions after `t` be ≥ 3% above the close of `t`?" with options `buy` / `skip`; `probability` = Jev's probability of `buy`.
- [ ] Answer open questions 1–3 first; pick parameters from the current docs (the `claude-api` skill for Claude).
- [ ] Tests: each decider maps a mocked answer to `Decision`; a malformed answer or an out-of-range probability raises.
- [ ] Done when: both are covered by tests, with no network and no secret.

### 4. `scripts/vn_stock_decide.py`

- [ ] For the session `t` of the analysis: `load_candidates` → for each symbol and each decider, one call → upsert into `vn_stock_decisions` (a rerun of a session overwrites its rows).
- [ ] One failed call does not stop the others; the script logs it and exits non-zero at the end.
- [ ] Writes a table to `$GITHUB_STEP_SUMMARY`: symbol, score, Claude decision and probability, Jev decision and probability.
- [ ] Log through `Logger`, including the token counts or cost per model.
- [ ] Tests with mocked deciders: all succeed, one fails among several, no candidate.
- [ ] **Manual run** on this machine against the local database with the user's keys (in the shell only): read the answers, adjust the prompt and the question.
- [ ] Done when: a manual run stores 2 × N rows for one session.

### 5. `scripts/vn_stock_decision_outcome.py`

- [ ] One SQL `UPDATE`: for rows with `hit` null whose symbol has a bar 5 sessions after `t` in `vn_stock_prices`, set `return_5 = close(t+5) / close(t) − 1` and `hit = return_5 ≥ 0.03`. Sessions counted from the symbol's own bars.
- [ ] Idempotent: run it every day; rows not due yet stay null.
- [ ] Tests on the real Postgres fixture: due, not due, exactly +3%, a halted symbol.
- [ ] Done when: running it twice gives the same table.

### 6. Workflow jobs

- [ ] Job `vn_stock_decide` in `.github/workflows/vn-stock-analysis.yml`: `needs: vn_stock_analyze`, `environment: production`, secrets `DATABASE_URL`, `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY`. Same boilerplate as the other jobs (pinned actions, `setup-env`, timeout).
- [ ] Job `vn_stock_decision_outcome`: `needs: install`, independent of the screen (it only needs prices), so it runs even on a day with nothing to screen.
- [ ] Both end with the `pipeline-state` action and are added to `notification`'s `needs`; neither is in `vn_stock_screen_done`'s `needs`.
- [ ] The user adds the two API keys to the `production` environment.
- [ ] README: files table and job list.
- [ ] Done when: a real `workflow_dispatch` run stores the decisions, shows the table in the job summary, and a wrong key fails only `vn_stock_decide`.

### 7. Measure, then adjust

- [ ] After about 20 sessions with outcomes (about 2 × 20 × 20 = 800 rows), one SQL report per model:
  - [ ] Hit rate of `buy` against the **base rate** (the share of all decided rows that reached +3%, whatever the decision). A model is only useful if its buys beat the base rate.
  - [ ] Calibration: bins of stated probability vs measured hit rate; Brier score.
  - [ ] Against two baselines: "buy every top-N symbol" and "buy the top 5 by score".
  - [ ] Claude vs Jev on the same rows.
- [ ] Adjust from the numbers: a calibration map (stated → measured probability), the buy threshold, the prompt / question; drop the model that loses on the same rows if the gap holds.
- [ ] Later inputs: the Phase 3 probability once that plan reaches a "go", more data sources as they arrive. Each change is measured the same way before it is kept.
- [ ] Set `N` and the cost ceiling (open question 4).
- [ ] Done when: the report exists and has been read once with real outcomes; `uv run pytest` ≥ 95% coverage, ruff clean.

## After Phase 2 (not planned yet)

An agent with a read-only SQL tool is only worth building if fixed inputs cannot answer your questions. It would need: a Postgres role with SELECT only and its own secret, a `READ ONLY` transaction with a timeout and a row limit, limits on turns and tokens, and a set of golden questions for evaluation. Write a separate plan then.
