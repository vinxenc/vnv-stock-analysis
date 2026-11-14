# RD-Agent: LLM-driven factor search

Status: **parked** (2026-11-14). Not to start before its prerequisites (below). Related: [logistic-regression-score.md](logistic-regression-score.md) (the baseline RD-Agent must beat), [foundation-model-forecasts.md](foundation-model-forecasts.md).

## Goal

Use [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) (MIT) as an **offline factor finder**: an LLM proposes factors, writes their code, backtests them in [Qlib](https://github.com/microsoft/qlib) and learns from each round. The factors that survive a held-out test and a human review become new indicators in `libs/analysis`. RD-Agent never runs in GitHub Actions and never touches the pipeline.

```
vn_stock_prices → Qlib data → RD-Agent (Linux machine) → candidate factors
  → human review of the code → one-time held-out test → libs/analysis indicator #25, #26, … (with tests) → forward check
```

## Why it is parked

- **Too little history.** `vn_stock_prices` starts on 2025-01-02 (about 1.8 years). An agent that tries hundreds of factors on that will find some that look good by chance; the published "about 2× annual return for under 10 USD" was measured on many years of Chinese A-shares, as reported by the authors.
- **No benchmark index** (VNINDEX) in the database.
- **No learned baseline yet.** If a logistic regression (or Qlib's LightGBM) on known indicators finds nothing, an agent will mostly find noise.

## Requirements (from the RD-Agent README, 2026-11)

- Linux only, Docker usable without `sudo`. The Mac M2 would run Qlib's x86 images under emulation (slow): use a Linux cloud VM.
- An LLM chat model and an embedding model through LiteLLM (OpenAI, Azure, DeepSeek, …): paid API keys.
- Data in Qlib's binary format.

## Phase 0. Prerequisites (gate)

- [ ] History backfilled to several years (for example from 2015) for the HOSE symbols, plus VNINDEX, through a new history fetcher and a seed migration (the daily sync only fetches the latest bar).
- [ ] The logistic regression plan has reached its phase 3 result (go or no-go), so there is a number to beat.
- [ ] The user agrees on an LLM budget per run and a provider.

## Phase 1. Qlib data and a non-LLM baseline

- [ ] Export `vn_stock_prices` to one CSV per symbol, convert with Qlib's `dump_bin.py` (`research/`, output git-ignored).
- [ ] Calendar from the sessions in the table (weekends and VN holidays already absent; `scripts/vn_holiday.py` for the future), instrument lists `hose` and `vn30`, VNINDEX as benchmark.
- [ ] Market rules in the Qlib config: price limit ±7% (`limit_threshold`), lot 100, no short selling, fees and tax, T+2 settlement.
- [ ] **Hold-out:** the last 6–12 months are never shown to the agent; they are used once, at the end.
- [ ] Baseline: Qlib Alpha158 + LightGBM, rolling retrain. Record IC, rank IC and the top-minus-bottom spread on the validation period. Below about 0.03 rank IC, stop here.

## Phase 2. RD-Agent environment

- [ ] Linux VM with Docker; `pip install rdagent`; `rdagent health_check`.
- [ ] `.env` with the chat and embedding models (keys never committed).
- [ ] Point the Qlib templates RD-Agent uses at the HOSE data (market, benchmark, train / valid / test segments ending before the hold-out).

## Phase 3. Factor search

- [ ] `rdagent fin_factor` only (factors alone). Not `fin_quant` (factor and model together) at first: more freedom means more overfitting on short data.
- [ ] Cap the number of loops and the spend; keep every run's log (the UI: `rdagent ui`).
- [ ] Keep the factors that beat the phase 1 baseline on the validation period.

## Phase 4. Review and port

- [ ] Read every kept factor's code: no look-ahead, economically sensible, not a near-copy of an existing indicator.
- [ ] Evaluate the kept factors **once** on the hold-out. Discard the ones that fail.
- [ ] Port the survivors to `libs/analysis` as indicators (pure function, a row in `scoring.py`, one test each, the 95% coverage gate), or as inputs of the logistic regression.

## Phase 5. Forward check

- [ ] The new indicators run in the daily pipeline for at least 3 months before their weight is raised; compare their rank IC with the hold-out result.

## Risks

- Overfitting / data snooping (the main one): mitigated only by the hold-out used once and the forward check.
- LLM cost drift: cap loops and spend per run.
- Licence of generated code: it is written for this repo, fine; but check any third-party code the agent copies in.
