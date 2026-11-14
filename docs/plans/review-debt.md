# Plan review debt

Open findings from the review of the plans on 2026-11-14 (a read-only review by Claude Fable 5.2 of PR #26, after the CodeRabbit and Sourcery threads were fixed in `5e08a7e`). None is fixed yet: they are to be worked through in later sessions.

**Rule:** before starting or changing any step of Phase 2 or Phase 3, read this file and fix the items that touch that step first (in the plan, then in the code). Tick an item when the plan says the right thing; write the commit next to it. Delete this file when every item is ticked.

Verified by the main session: items 10 (`setup-env` and the CI audit) and 12 (21 columns). The others are the reviewer's, checked against the files by the reviewer, not yet re-checked.

## Gate: settle before starting

- Phase 2 steps 1–4 and 6–7 may start once items 4, 5 and 6 are in the plan (done, `298e9d1`).
- Phase 2 step 5 (TabICL), the retry workflow of step 8 and step 9 need items 1, 2, 3, 8 and 9 first.
- Phase 3 steps 0–2 may start once items 2 and 12 are in the plan; items 3 and 7 before step 3.

## High

- [ ] **1. Phase 2 step 9 tunes on about 4 independent periods** (`phase-2-llm-decision.md`, step 9 and the footer item of step 7). 20 sessions of overlapping 5-session labels on 20 correlated symbols is not 1,200 observations. Fix: 20 sessions is a sanity check only; adjust or drop nothing before about 60 sessions; measure per session (buy hit rate minus that session's base rate) with a non-overlapping t-stat; no "last month's hit rate" in the Telegram footer until then.
- [ ] **2. Deciders and backtests are measured on different populations** (`phase-2` step 5 and step 9 vs `phase-3-logistic-regression-score.md` step 1 and the base-rate item). Phase 2 decides the top 20 by score; TabICL's backtest and Phase 3 cover the whole liquid universe (about 90 symbols). `t+5` is defined only in Phase 2 (fifth market session). Fix: Phase 3 and the TabICL backtest also report every metric on the top-20-by-score rows of each session; define `t+5` once in `libs/decision/panel.py` and reuse it in the outcome job.
- [ ] **3. The go / no-go does not fit `hit_3pct_5`** (`phase-3` Decisions, step 3). The label follows market direction: logistic on per-session z-scores cannot see the market level, LightGBM on raw inputs can fit regimes on about 75 periods, so pooled AUC is not comparable between them; rank IC is cross-sectional while Phase 2 uses an absolute threshold. Fix: for `hit_3pct_5`, judge on what Phase 2 measures: precision of buys against the same-session base rate, and Brier score against a base-rate predictor, with sessions as the unit.

## Medium

- [x] **4. A decision can be rewritten after its outcome is known** (`phase-2` Decisions, step 8 retry). Delete-then-insert plus a retry for any stored session has no guard; late rows count like timely ones. Fix: the retry refuses a session that is not the newest in `vn_stock_prices`, or step 9 excludes rows whose `created_at` is after the next session's open. Done in the plan: `298e9d1`.
- [x] **5. The notify job fires when `vn_stock_analyze` failed** (`phase-2` step 8). `if: always()` plus "screened" sends a message from empty or stale rankings, and it cannot read `screened` without `vn_stock_screen` in its `needs`. Fix: `needs: [vn_stock_screen, vn_stock_analyze, <three decide jobs>]`, `if: always() && needs.vn_stock_analyze.result == 'success'`. Done in the plan: `298e9d1`.
- [x] **6. Stale decisions sent as fresh** (`scripts/vn_stock_screen.py` processes one session per run). After a failed day each scheduled run handles the previous session until someone dispatches by hand; a session redone because `vn_stock_screen_done` failed pays the APIs again and sends a second message. Fix: decide and notify compare `t` with `max(date)` in `vn_stock_prices`; if older, skip the deciders or mark the message "late". Done in the plan: `298e9d1`.
- [ ] **7. Phase 3 picks its configuration from the test months** (`phase-3` steps 3 and 4: "shrink it further", the 6-theme rerun, the step 4 rerun). 2 models × 2 labels × 3 input sets against t ≥ 2 on about 12 test months: one will pass by chance. Fix: name one primary configuration up front (logistic, `beat_median`, base inputs); keep the last 3 months untouched and use them once, as Phase 5 does.
- [ ] **8. TabICL's prerequisites and bar** (`phase-2` Status, Prerequisites, step 5). It needs Phase 3 steps 1–3 (the walk-forward helper and the results to compare), not only step 1, and it ships whatever its backtest says while logistic and LightGBM must pass a go / no-go. Fix: list steps 1–3 as prerequisites and apply the same go / no-go, or state that TabICL ships as an experiment.
- [x] **9. The retry workflow duplicates four jobs** (done in the plan, 2026-11-14: the retry workflow and `--session` are dropped, "Re-run failed jobs" on the original run reuses the filter's JSON artifact; still to be tested in step 8's done-when) (`phase-2` Decisions, step 8; over-engineering). GitHub's "Re-run failed jobs" on the original run reruns the failed decider and its notify job, with that run's artifacts and current secrets, within the 7-day artifact retention (not tested). Fix: drop `vn-stock-decide.yml` and `--session`; if older sessions must be retried, one reusable workflow (`workflow_call`), not copied jobs. Check item 4 together with this one: its "newest session only" guard (done, `298e9d1`) applies to whichever retry stays.
- [ ] **10. Dependency groups do not fit the plumbing** (`phase-2` Decisions and step 5, `phase-3` step 0 and Decisions). `.github/actions/setup-env/action.yml` only knows `dev` / `--no-dev` and two cache suffixes, so no job can install a `tabicl` group; CI's audit exports `--no-dev` only, so "`pip-audit` covers it" is false; `panel.py` and `TabICLDecider` sit in `libs/` under the 95% gate while CI installs neither `research` (pandas) nor `tabicl` (torch). Fix: a `groups` input and cache suffix in `setup-env`, export the group in the audit, `panel.py` uses only main dependencies, torch imported lazily.

## Low

- [ ] **11. A wrong outcome is permanent** (`phase-2` step 6, `phase-1-sql-screens.md` Notes). Stored closes are adjusted as of the day stored, so an ex-rights date between `t` and `t+5` gives a fake miss, and the job only touches rows where `hit` is null. The sync starts at 14:45 VN, before the 15:00 close; the label now depends on that bar being final. Fix: leave the outcome null when any one-day change between `t` and `t+5` is beyond ±7% (Phase 3 step 4's rule); spot-check a few stored closes against the final close.
- [ ] **12. 21 inputs, not 20** (`phase-3` Decisions "Option B", step 3 title, step 4). 24 minus #5 and #17 is 22, #1 and #19 share one value; the table lists 21 columns. Fix: correct "20" everywhere.
- [ ] **13. Step 5b contradicts per-session standardisation** (`phase-3` Decisions vs step 5b). Inputs are z-scored per session, so there are no "standardisation parameters" to store, and daily scoring needs that day's whole shortlist. Fix: store coefficients only; z-score across the day's shortlist inside `vn_stock_analyze`.
- [ ] **14. The look-ahead check cannot match exactly** (`phase-3` step 1 vs `SESSIONS = 260` in `scripts/vn_stock_get_history.py`). RSI and PPO are recursive, so "all bars up to t" differs slightly from the live run's last 260 rows; the check only covers sessions since 2026-11-11. Fix: `build_panel` uses the same last-260 window and compares with a tolerance.
- [ ] **15. Cuts and stale claims:**
  - [x] `phase-2` step 1: the `decider` Postgres enum needs `ALTER TYPE` for the fourth decider already planned; a text column with a CHECK is enough. Done in the plan: `af34bf6`.
  - [ ] `phase-2` step 7: the 4096-character split is unreachable with 20 one-line symbols; drop it.
  - [ ] `phase-2` Decisions: the ranked table and the `vn-stock-analysis` artifact are already public (`vn-stock-analysis.yml`), so only buy / skip is hidden; say so.
  - [ ] `phase-2` step 8: four new secrets, not five (`DATABASE_URL` exists).
  - [x] `README.md` (row of `vn_stock_analyze`) and `libs/analysis/models.py` (docstring) still say Phase 2 reads the JSON. It is true again: the filter job of Phase 2 reads `out/vn_stock_analysis.json` (plan, 2026-11-14); only the README row needs a mention of the filter in step 8.

## Not verified by anyone yet

Jev's API (endpoint, question format), TabICL's CPU time and memory on a GitHub runner, and the production database contents. The plans leave these as open questions or measurement steps.
