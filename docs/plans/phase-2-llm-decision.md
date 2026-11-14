# Phase 2 — Buy / skip decision per symbol (Claude, Jev, TabICL) and a Telegram channel

Status: **draft, not started** (2026-11-14; first draft 2026-10-28 was a market summary, replaced). Comes after [phase-1-sql-screens.md](phase-1-sql-screens.md), which has run green on GitHub since 2026-11-11. Work through the checklist below in order: one step = one PR. **Open review findings in [review-debt.md](review-debt.md): read them before starting a step.** The TabICL step needs the feature panel of [phase-3-logistic-regression-score.md](phase-3-logistic-regression-score.md) step 1.

## Goal

For each symbol of the day's Phase 1 ranking with a score of 40 or more, **three deciders answer buy or skip, with a probability**, in three pipelines (GitHub Actions jobs) that run one after another, `llm` then `decision_model` then `tabular`, and start only once a filter job has written the day's input as one JSON file:

| Decider | Kind | Reads | Runs |
|---|---|---|---|
| **Claude** | LLM, API | one symbol's data as JSON | API call per symbol |
| **Jev** (TypeSafe) | decision model, API | the same JSON as state, one typed question | API call per symbol |
| **TabICL** | tabular foundation model, open source (BSD-3) | the symbol's feature row, with the labelled history of all symbols as context | on the runner's CPU |

Every answer is stored in `vn_stock_decisions`; five sessions later the outcome is filled in, so the three are measured on the same rows. Once all three have answered, **one Telegram message** with the session's decisions goes to one channel.

The decisions are the system's output for the user to screen with; the user decides what to trade.

## Prerequisites

- [x] Phase 1 has run reliably for a few days (green runs on 2026-11-11, 12 and 13; the one cron failure, 11-12, was a false alarm: GitHub started the run after midnight VN).
- [ ] Accounts and keys, created by the user and never seen by Claude: Anthropic API key, TypeSafe (or reseller) key for Jev, a Telegram bot (BotFather) and the channel it posts to (bot added as admin), its chat id.
- [ ] For TabICL only: Phase 3 step 1 (`libs/decision/panel.py`) is built.

## Decisions and open items

Decided by the user (2026-11-14):
- **Per symbol, independent:** one answer per symbol and decider; no market overview, no comparison between symbols in one answer.
- **Three deciders in a chain** (Claude, then Jev, then TabICL), started only after the filter job (below) has written the day's input JSON; all stored in the same table.
- **A buy is right** when `close(t+5) ≥ close(t) × 1.03`: the close 5 sessions after the session decided (`t`) is at least 3% above the close of `t`. Sessions, not calendar days.
- **Inputs today:** the day's analysis (`out/vn_stock_analysis.json`: score, themes, indicators with raw values, flags) and the last 60 bars of each symbol from the history (`out/vn_stock_history/`), both artifacts of the same run, combined by the filter job into one JSON file. More sources later are more fields, not a new design.
- **"Adjusted over time"**: for Claude and Jev, what is around them (calibration map from stated to measured probability, buy threshold, prompt / question), since their weights cannot be trained here; for TabICL, the context grows by itself as outcomes arrive.
- **Delivery: one Telegram channel**, one message per session.

Decided while writing this plan (change if wrong):
- **A filter job picks the day's candidates** (user, 2026-11-14). New job `vn_stock_decision_filter` in `vn-stock-analysis.yml`, `needs: vn_stock_analyze`. `vn_stock_analyze` exposes the session it analysed (`as_of` of its report) as a job output `session`; the filter job takes that date as the day to work on and fails if the report's `as_of` differs. It keeps the symbols with `score >= 40` (one constant, `MIN_SCORE`; the same for the three deciders; a symbol without a score is dropped) and writes `out/vn_stock_decision_input.json` (artifact `vn-stock-decision-input`): `{"session": "<t>", "symbols": [...]}`, each symbol with its score, coverage, turnover, themes, indicators, flags and last 60 bars up to `t`, in ranking order. The decide jobs and the notify job read that file; no job picks candidates from the database. It reads the JSON of the same run, not `vn_stock_rankings`, so a symbol that left the shortlist on a rerun can never come back as a candidate, and `vn_stock_analyze` needs no change beyond the output. The file holds the same public data as the `vn-stock-analysis` artifact and no decision. No symbol at 40 or more: the file has an empty list, the decide jobs store nothing, no message is sent.
- A model's rows for `t` (same `model_name`) always reflect its **latest** run: each run replaces them (delete, then insert its successes, in one transaction), so a symbol that failed on a rerun has no row and shows `—`, never an older answer.
- A failed decision is retried with GitHub's "Re-run failed jobs" on the original run (review-debt item 9): it reruns the failed decider and every job that depends on it (the later deciders of the chain and the notify job, so those are paid again and the message is sent again) with that run's artifacts, so the filter's JSON is reused, and current secrets, within the 7-day artifact retention. No separate retry workflow, no `--session`. Only the newest session can be retried (next point). To be tested in step 8's done-when.
- **Only the newest session is decided, sent or retried** (review-debt items 4 and 6). `t` (the `session` of the input JSON) must equal `max(date)` in `vn_stock_prices`; `vn_stock_decide.py` and `vn_stock_decision_notify.py` check it first, with one helper `is_latest_session(engine, t)` in `libs/decision/candidates.py`. Why: `vn_stock_screen` handles one session per run, so after a failed day the next scheduled runs handle an older session until someone dispatches by hand, and the sync has already stored newer bars. Deciding then would send stale decisions as fresh and pay the APIs for them. The same rule stops a retry from rewriting a decision after its outcome is known (a decision replaced after `t+5` would be scored on a price it could see). An older `t` is skipped: no API call, no row, no message, exit 0, the job summary says "stale session, skipped" (a re-run of a failed job after the next sync therefore changes nothing). A retry is possible only until the next sync (15:15 VN of the next working day) stores a newer session; after that the session stays as stored.
- **The decisions are not printed in the job summary or the log.** The repository is public, so its job summaries, logs and artifacts are readable by anyone; the decisions go only to the database and the Telegram channel. The job summary shows counts only (symbols decided, buys per decider, failures).
- **A decider is a kind plus a model** (2026-11-14): the column `decider` holds the kind, `llm` (Claude), `decision_model` (Jev) or `tabular` (TabICL; later Phase 3's logistic regression and LightGBM), and `model_name` the model, free text in the form `provider/model` (`anthropic/claude-opus-5-5`, `typesafe/jev`, `tabicl/v2`). `model_name` is part of the primary key, so two LLMs can answer the same symbol; a new model of a known kind needs no migration, a new kind does (`CLAUDE.md`). The prompt or question version goes into `input`, not into a column; `model_name` is set once per decider class, in code.
- One script for the three pipelines, `scripts/vn_stock_decide.py --decider llm|decision_model|tabular`; three jobs run it one after another (`llm`, then `decision_model`, then `tabular`: the order in which they are implemented; until step 4 the `decision_model` job and until step 5 the `tabular` job are placeholders that only echo a message). Each later job has `needs: [vn_stock_decision_filter, <the job before it>]` and `if: always() && needs.vn_stock_decision_filter.result == 'success'`, so it runs whatever the job before it did, and one decider failing never blocks the others.
- The decide jobs are a chain hanging off `vn_stock_decision_filter`, so no decider starts before the day's input JSON is written; the filter and the chain are **not** in `vn_stock_screen_done`'s `needs`, so an API outage never leaves the session due.
- The Telegram job sends whatever is stored, even when a decider failed (its column says so); only a Telegram error fails that job. It does **not** run when `vn_stock_decision_filter` did not succeed, which includes a failed or skipped `vn_stock_analyze` (a day off, nothing to screen, a failed sync): it would send a message from empty or stale data (review-debt item 5). A skipped `vn_stock_analyze` already covers "not screened": its need `vn_stock_get_history` is skipped when `vn_stock_screen` reports `screened=false`, so the job needs no `screened` output. The candidates of its message come from the input JSON, not from the database.
- Telegram is called with `niquests` (already a dependency), no Telegram library.
- TabICL's dependencies (torch CPU build, `tabicl`) go in their own dependency group, installed only by its job; the other jobs keep their light `--no-dev` install. Its checkpoint is cached with `actions/cache`.
- Known limits of the label: the decision is made after the close of `t`, so `close(t)` is not a price anyone could still buy at; the label is optimistic by one session's move. Adjusted prices skew an ex-rights week (Phase 1 Notes). A halted symbol with no bar at `t+5` keeps an empty outcome.

Open questions (each blocks the step named):
1. Claude model, `anthropic` SDK vs `niquests` (SDK is the default), language of Claude's reason (Vietnamese?). (step 3)
2. Jev endpoint: TypeSafe's own API or a reseller (OpenRouter, AI/ML API); the sources disagree on the URL. (step 4)
3. TabICL version (v2 by default) and the context size (all labelled rows, or the last K sessions), from the time measured on the runner. (step 5)
4. Message language and layout in Telegram (one line per symbol by default). (step 7)
5. Daily cost ceiling, the final `MIN_SCORE` (40 to start) and whether to cap the symbols per day, since the number of candidates now varies with the market. (step 9)

## Checklist

### 1. Table `vn_stock_decisions`

- [x] Migration `0009`: table `vn_stock_decisions`, primary key (`date`, `symbol`, `model_name`). Columns: `model_name` (text, `provider/model`, no CHECK: a new model needs no migration), `decider` (`text`, the kind, `CHECK` in `llm` / `decision_model` / `tabular`; a new kind is a new migration, see `CLAUDE.md`), `decision` (`text`, `CHECK` in `buy` / `skip`), `probability` (`CHECK` between 0 and 1, the probability of buy), `reason` (text, LLM only), `input` (JSONB: the exact input with the prompt or question version, so any answer can be re-read; for TabICL the row and the context size, not the context), `created_at`, and the outcome: `return_5` and `hit` (null until known).
- [x] SQLModel class `DecisionRecord` in `libs/db/models.py` (not `Decision`: step 2 uses that name for the answer a decider returns); the enums `Decider` and `Verdict` (buy / skip) in `libs/decision/models.py`; the migration names the table as a string (`CLAUDE.md`); the three CHECKs (`ck_vn_stock_decisions_decider`, `_decision`, `_probability`) are in the model's `__table_args__` and in the migration; a test inserts a bad `decider`, a bad `decision`, a `probability` of 1.3 and a duplicate key and expects Postgres to refuse each (`alembic check` ignores CHECK constraints).
- [x] Done when: `alembic upgrade head` on a fresh local database creates it and `alembic check` is clean.

### 2. Shared parts: candidates, input, interface, script

- [x] `libs/decision/candidates.py`: `MIN_SCORE = 40`; `build_input(report, history_dir)` → the symbols of the `AnalysisReport` with `score >= MIN_SCORE`, in the report's order, each with its last 60 bars from `out/vn_stock_history/<SYMBOL>.json` up to the session, never after; `write_input` / `read_input` for `out/vn_stock_decision_input.json` (`{"session", "symbols"}`, pydantic models). No database.
- [ ] Next to them, `is_latest_session(engine, t)`: `t == max(date)` in `vn_stock_prices` (see "Decisions"), with its test on the Postgres fixture. Needed by the decide script, not by the filter.
- [x] `scripts/vn_stock_decision_filter.py <session>`: reads `out/vn_stock_analysis.json` and the history, exits 1 when the report's `as_of` is not `<session>` (the `session` output of `vn_stock_analyze`), writes the input JSON, job summary: counts only (symbols kept of symbols scored).
- [ ] `libs/decision/base.py`: `Decision(decision, probability, reason)` and the interface `Decider` (class attributes `decider` kind and `model_name`; `decide_all(t, candidates) -> dict[symbol, Decision]`) (TabICL scores all candidates in one pass; the API deciders loop inside). Same pattern as `Indicators` in `libs/indicators`.
- [ ] `scripts/vn_stock_decide.py --decider <name>`: `read_input` (`t` is its `session`) → `is_latest_session`: an older `t` is skipped (exit 0, "stale session, skipped") → no symbol in the file: nothing to do, exit 0 → the decider → in one transaction, delete that model's rows for `t` (its `model_name`) and insert this run's successes. One failed symbol does not stop the others; the script exits non-zero at the end if any failed. Job summary: counts only.
- [ ] Log through `Logger` (no decisions in the log, see "Decisions"), including the token counts or cost.
- [x] Filter tests (no database): a score of exactly 40 kept, 39.9 dropped, a symbol without a score dropped, the report's order kept, no bar after `t` in the output, the last 60 bars only, a session that differs from the report's `as_of` fails, an empty list when nobody reaches 40.
- [ ] Decide-script tests on the real Postgres fixture with a fake decider: one symbol failing, an empty input, a rerun replaces the rows, a rerun where a symbol fails leaves that symbol without a row, a session older than `max(date)` (skipped, no row written).
- [ ] Done when: the filter script, run on the `out/` of a local analysis, writes the JSON, and the decide script runs end to end on it with the fake decider.

### 3. Claude decider

- [ ] Answer open question 1; pick the model and parameters from the current API docs (the `claude-api` skill).
- [ ] `ClaudeDecider`: one call per symbol, structured JSON output `{decision, probability, reason}`. The prompt states the target (+3% in 5 sessions) so the probability means that; judge only from the data given; invent nothing (news, financials, other symbols); report an `unavailable` indicator as such.
- [ ] Tests with a mocked client: a good answer, a malformed one, a probability out of range, an API error.
- [ ] **Manual run** against the local database with the user's key (in the shell only): read the answers, adjust the prompt.
- [ ] Done when: tests pass and a manual run stores N rows.

### 4. Jev decider

- [ ] Answer open question 2 from the official docs.
- [ ] `JevDecider`: the same JSON as state, one typed question "will the close 5 sessions after `t` be ≥ 3% above the close of `t`?" with options `buy` / `skip`; `probability` = Jev's probability of `buy`.
- [ ] Tests with a mocked HTTP client: a good answer, a malformed one, an API error.
- [ ] Manual run with the user's key.
- [ ] Replace the placeholder step of the `vn_stock_decide_decision_model` job (step 8) with the real run: `scripts/vn_stock_decide.py --decider decision_model` and the Jev key as a secret.
- [ ] Done when: tests pass, a manual run stores N rows, and the `decision_model` job stores N rows instead of echoing.

### 5. TabICL decider

- [ ] Dependency group `tabicl` (torch from the CPU index, `tabicl`); `uv.lock` refreshed; `pip-audit` covers it.
- [ ] `TabICLDecider`: context = the rows of `build_panel` (Phase 3 step 1) whose `hit_3pct_5` is known, i.e. sessions up to `t − 5`, never later (their label would need bars after `t`); query = the candidates' rows for `t`. `probability` = P(`hit_3pct_5` = 1); buy when above a threshold (0.5 to start, set in step 9).
- [ ] **Backtest before trusting it** (TabICL, unlike Claude and Jev, can be tested on the past): the walk-forward of Phase 3 step 2 with `hit_3pct_5`; compare with the base rate and with Phase 3's logistic and LightGBM; results into this file.
- [ ] Measure time and memory on a GitHub runner (4 vCPU, 16 GB) with a `workflow_dispatch` test job; set `timeout-minutes` and the context size from it (open question 3).
- [ ] Tests: the context never holds a row whose label needs a bar after `t`; a mocked model maps to `Decision`.
- [ ] Replace the placeholder step of the `vn_stock_decide_tabular` job (step 8) with the real run: `scripts/vn_stock_decide.py --decider tabular`, the `tabicl` dependency group in `setup-env` (review-debt item 10), the checkpoint cache, `DATABASE_URL`, and the `timeout-minutes` measured above.
- [ ] Done when: the backtest numbers are in this file, one run on the runner fits in its timeout, and the `tabular` job stores N rows instead of echoing.

### 6. Outcome job

- [ ] `scripts/vn_stock_decision_outcome.py`: one SQL `UPDATE` for rows with `hit` null. `t+5` is the fifth **market** session after `t` (the fifth distinct date after `t` in `vn_stock_prices`, all symbols); the row is filled only when the symbol has a bar on that exact date: `return_5 = close(t+5) / close(t) − 1`, `hit = return_5 ≥ 0.03`. A symbol halted on `t+5` keeps an empty outcome, even if it trades again later (counting its own bars would pick a later bar).
- [ ] Idempotent: rows not due yet, or whose bar is not stored yet, stay null and are picked up by a later run.
- [ ] Tests on the real Postgres fixture: due, not due, exactly +3%, a symbol halted on `t+5` that trades on `t+6`.
- [ ] Done when: running it twice gives the same table.

### 7. Telegram message

- [ ] `scripts/vn_stock_decision_notify.py`: reads the input JSON (`read_input`); first `is_latest_session` (same rule as the decide script: skipped, nothing sent, exit 0); an empty list also sends nothing; then left-joins the symbols with their rows of `vn_stock_decisions` for `t`, so a candidate every decider failed on still gets its line (three `—`); then sends one message with the Bot API `sendMessage` (`niquests`, `parse_mode` HTML with escaping). Secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- [ ] Layout: header with the session date; one line per symbol in ranking order with its score and each decider's decision and probability (`—` when that decider failed or did not run); a footer with buys per decider, last month's measured hit rate per decider once step 9 has numbers, and a one-line "for reference only".
- [ ] Split at Telegram's 4096-character limit; retry once on a network error, then fail the job.
- [ ] The token is never logged (it is part of the URL: log the method, never the URL).
- [ ] Tests with a mocked HTTP client: one message, a split message, a missing decider, Telegram returning an error, a session older than `max(date)` (nothing sent).
- [ ] Manual run to the real channel with the user's token.
- [ ] Done when: the channel receives a readable message for a real session.

### 8. Workflow wiring

- [ ] In `.github/workflows/vn-stock-analysis.yml` (the `session` output and the `vn_stock_decision_filter` job are done; the decide jobs and the notify job are not): `vn_stock_analyze` gets an output `session`, set by a step after the script from the report (`jq -r .as_of out/vn_stock_analysis.json`). New job `vn_stock_decision_filter` (`needs: vn_stock_analyze`): downloads the `vn-stock-analysis` and `vn-stock-history` artifacts, runs `scripts.vn_stock_decision_filter ${{ needs.vn_stock_analyze.outputs.session }}`, uploads `out/vn_stock_decision_input.json` as `vn-stock-decision-input` (7 days); no database, so no `environment` and no secret. Then three chained jobs `vn_stock_decide_llm` (`needs: vn_stock_decision_filter`), `vn_stock_decide_decision_model` (`needs: [vn_stock_decision_filter, vn_stock_decide_llm]`), `vn_stock_decide_tabular` (`needs: [vn_stock_decision_filter, vn_stock_decide_decision_model]`); each downloads the input artifact; the two later ones have `if: always() && needs.vn_stock_decision_filter.result == 'success'`; each `environment: production`, `DATABASE_URL` plus its own key (TabICL needs none; it restores the checkpoint cache). Same boilerplate as the other jobs (pinned actions, `setup-env`, timeout). Until its step is done, `vn_stock_decide_decision_model` (step 4) and `vn_stock_decide_tabular` (step 5) are **placeholders**: one step that runs `echo "<decider> decider: not implemented yet (Phase 2 step <4 or 5>)"`, no secret, no database, no row written, always green. They are created now so the chain, the notify job's `needs` and the `notification` `needs` are final from the start; their columns in the message show `—`. Only `vn_stock_decide_llm` is real from the first run.
- [ ] Job `vn_stock_decision_notify`: `needs: [vn_stock_decision_filter, vn_stock_decide_llm, vn_stock_decide_decision_model, vn_stock_decide_tabular]`, `if: always() && needs.vn_stock_decision_filter.result == 'success'`, so it runs when one decider failed but not when the filter (or the analysis before it) failed or was skipped; downloads the input artifact; secrets `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- [ ] Job `vn_stock_decision_outcome` in `.github/workflows/vn-stock-prices-sync.yml`, `needs: vn_stock_daily_price_store`: it runs right after the bars it needs are stored, every working day, whether or not the analysis screens anything.
- [ ] No retry workflow: a failed decider is retried with "Re-run failed jobs" on the original run (see "Decisions"; review-debt item 9).
- [ ] All end with the `pipeline-state` action and go into their workflow's `notification` `needs`; none in `vn_stock_screen_done`'s `needs`.
- [ ] The user adds the five secrets to the `production` environment.
- [ ] README: files table and job list.
- [ ] Done when: a real `workflow_dispatch` run stores N rows (Claude only; 2 × N once step 4 replaces the `decision_model` placeholder, 3 × N once step 5 replaces the `tabular` one), the channel gets the message, and a wrong Anthropic key fails only `vn_stock_decide_llm` while the two placeholder jobs still run and the message still arrives with Claude's column empty; then, after the key is fixed, "Re-run failed jobs" on that run fills Claude's rows from the same input artifact and resends the message; a day with a failed `vn_stock_analyze` sends no message; a re-run after a newer session is stored changes nothing ("stale session, skipped"); a day where nobody scores 40 or more stores nothing and sends nothing.

### 9. Measure, then adjust

- [ ] After about 20 sessions with outcomes (about 3 × 20 × 20 = 1,200 rows), one SQL report per decider:
  - [ ] Hit rate of `buy` against the **base rate** (the share of all decided rows that reached +3%, whatever the decision). A decider is only useful if its buys beat the base rate.
  - [ ] Calibration (bins of stated probability vs measured hit rate) and Brier score.
  - [ ] Against two baselines: "buy every symbol at 40 or more" and "buy the top 5 by score"; and the three deciders against each other on the same rows.
- [ ] Adjust from the numbers: a calibration map per decider, the buy thresholds, Claude's prompt and Jev's question, TabICL's context size; drop a decider that keeps losing on the same rows.
- [ ] Add Phase 3's kept model (logistic or LightGBM) as a `tabular` model (a new `model_name`, no migration) once that plan reaches a "go" (its step 5c).
- [ ] Set `MIN_SCORE`, a cap on symbols per day if needed, and the cost ceiling (open question 5).
- [ ] Done when: the report has been read once with real outcomes; `uv run pytest` ≥ 95% coverage, ruff clean.

## After Phase 2 (not planned yet)

An agent with a read-only SQL tool is only worth building if fixed inputs cannot answer your questions. It would need: a Postgres role with SELECT only and its own secret, a `READ ONLY` transaction with a timeout and a row limit, limits on turns and tokens, and a set of golden questions for evaluation. Write a separate plan then.
