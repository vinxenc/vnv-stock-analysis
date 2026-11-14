# Phase 4 — Forecasting foundation models (Kronos, Chronos-2, TiRex-2): results and reference

Status: **reference** (2026-11-14). Zero-shot backtests done; none is good enough to enter the score. TiRex-2 is the only candidate worth a forward test, not started (where it runs is undecided). **The research code below (`research/kronos_backtest.py`, `research/online_correction.py`, the vendored `research/kronos/`, the dependency group `kronos`) was not committed**: this file keeps its design and results; rebuild it from the description if a model is revisited. Related: [phase-3-logistic-regression-score.md](phase-3-logistic-regression-score.md), [phase-5-rd-agent.md](phase-5-rd-agent.md).

## The models

| | [Kronos](https://github.com/shiyu-coder/Kronos) | [Chronos-2](https://github.com/amazon-science/chronos-forecasting) | [TiRex-2](https://github.com/NX-AI/tirex-2) |
|---|---|---|---|
| Made for | financial candles only | any time series | any time series (multivariate, covariates) |
| Input used here | OHLCV | close only | close only |
| Output used here | mean of sampled candles | median of the quantiles | median of 9 quantiles (0.1..0.9) |
| Size | small 25M, base 102M | 120M | 38M active (univariate) |
| Install | not on PyPI: `model/` vendored in `research/kronos/` at commit `67b630e`, import made relative | `pip install chronos-forecasting` | `pip install tirex-2` |
| Licence | MIT (code and weights) | Apache-2.0 | Apache-2.0 |
| VN30 backtest time (Mac M2) | small ≈ 25 min, base ≈ 2 h+ (MPS, `--chunk 10`) | ≈ 35 s (CPU) | ≈ 2 min (CPU) |

All four are optional: dependency group `kronos` (torch, chronos-forecasting, tirex-2), never installed by `uv sync` or CI.

## How to rerun

`research/kronos_backtest.py` (walk-forward, no look-ahead: only bars up to t go in). `--model` picks the family: a name containing `chronos` → Chronos, `tirex` → TiRex-2, anything else → Kronos (`--tokenizer` for Kronos). `--symbols` tests given symbols instead of the `--universe` most liquid ones per session.

```bash
export DATABASE_URL=postgresql+psycopg://vnv:vnv@localhost:5432/vnv HF_HUB_OFFLINE=1   # offline once the weights are cached
uv run --group kronos python -m research.kronos_backtest --model NX-AI/TiRex-2 --symbols ACB BID ... --sessions 200 --step 1 --out out/vn30/tirex-2
```

- Hugging Face downloads once hung for 6 minutes (`CLOSE_WAIT`): set `HF_HUB_OFFLINE=1` after the first download, or copy the snapshot to `models/` (git-ignored) and pass the path.
- Kronos-base ran out of MPS memory with 50 series × 5 samples on 16 GB: `--chunk 10`.
- zsh does not split `$VAR` into words: write `${=VAR}` or the arguments inline.
- Metrics: hit rate, rank IC per session (+ t-stat), top-fifth minus bottom-fifth return, MAE vs the random walk (forecast 0). **For h > 1 with `--step` < h the windows overlap and the t-stat is inflated**: recompute it on non-overlapping sessions (every h-th session).

`research/online_correction.py` post-processes a `predictions.csv` (`--step 1`) with a black-box online correction learned from resolved errors only (bias shift, and a linear `actual ≈ a + b × forecast`), the simplest form of ORCA / COSA / TAFAS.

## Results (data up to 2026-11-09)

Random-walk MAE is the bar: a forecaster that does not beat "the price stays" has no level skill.

### Top 50 liquid symbols per session (98 sessions, step 2, 23,645 forecasts)

| Model | h1 IC (t) | h1 MAE | h5 IC (t) | h5 MAE |
|---|---|---|---|---|
| Kronos-small | 0.008 (0.36) | 0.0243 | 0.020 (0.76) | 0.0672 |
| Kronos-base | 0.010 (0.40) | 0.0344 | 0.023 (0.79) | 0.0949 |
| Chronos-2 | −0.037 (−2.20) | 0.0177 | −0.007 (−0.42) | 0.0410 |
| TiRex-2 | 0.034 (1.65) | 0.0167 | 0.074 (3.44, overlapping) | 0.0394 |
| random walk | | 0.0165 | | 0.0396 |

### VN30 as of 2026-08-03 (195 sessions, step 1; 28 of 30 symbols, TCX too short)

| Model | h1 IC (t) | h1 MAE | h3 IC (t) | h5 IC (t) | h5 MAE | h5 long-short |
|---|---|---|---|---|---|---|
| Chronos-2 | 0.003 (0.25) | 0.0161 | −0.023 (−1.59) | −0.018 (−1.23) | 0.0362 | −0.29% |
| TiRex-2 | 0.028 (1.77) | 0.0154 | 0.041 (2.30) | 0.047 (2.49) | 0.0346 | +0.63% |
| Kronos-small | 0.028 (1.75) | 0.0212 | 0.034 (1.88) | 0.058 (3.18) | 0.0580 | +0.22% |
| Kronos-base | stopped at 30 / 195 | | | | | |
| random walk | | 0.0152 | | | 0.0348 | |

TiRex-2 t-stats on **non-overlapping** sessions: h1 1.77, h3 1.38, h5 1.10 (all below 2). Chronos-2: h5 −0.54.

VN30 list (SSI and VNDirect APIs agreed, 2026-11-14): ACB BID BSR CTG FPT GAS GVR HDB HPG LPB MBB MCH MSN MWG SAB SHB SSB SSI STB TCB TCX VCB VHM VIB VIC VJC VNM VPB VPL VRE.

### Single symbols (195 sessions, step 1)

| Symbol | Model | h1 hit | h1 MAE | h5 hit | h5 MAE | random walk h1 / h5 |
|---|---|---|---|---|---|---|
| CTD | Chronos-2 | 49.2% | 0.0172 | 53.9% | 0.0421 | 0.0165 / 0.0406 |
| CTD | Kronos-small | 51.4% | 0.0221 | 52.8% | 0.0615 | |
| CTD | Kronos-base | 51.9% | 0.0351 | 53.9% | 0.0994 | |
| DXG | Chronos-2 | 46.7% | 0.0188 | 42.8% | 0.0432 | 0.0169 / 0.0409 |
| DXG | Kronos-small | 50.3% | 0.0214 | 55.6% | 0.0520 | |
| DXG | Kronos-base | 44.9% | 0.0314 | 49.2% | 0.0992 | |

No result is significant (binomial p ≥ 0.07). Chronos-2 leans up: it forecast a rise on 61% (CTD) and 75% (DXG) of sessions at h1, against 45% and 42% real up days. CTD looked like 7/8 right for Chronos-2 on the 8 sessions it was in the top 50; on 195 sessions it is 49%.

### Online correction (Chronos-2, CTD and DXG, windows 20 / 40 / 80)

No stable gain: h1 MAE moves toward the random walk but never beats it (best: DXG linear, window 80, 0.0162 vs 0.0159); h5 MAE gets worse (chasing past trends); hit rates move ±5 points with no consistent sign. Conclusion: the problem is no signal, not bias, so the published test-time-adaptation methods were not tried.

## Conclusions

- No zero-shot model ranks HOSE stocks well enough to enter the score.
- Kronos: worst level accuracy (bigger is worse), slow, vendored code. Dropped.
- Chronos-2: closest to the random walk, fastest, no ranking signal. Kept only as a reference.
- TiRex-2: the only one with a consistently positive IC in both universes and level accuracy at the random walk, but not significant once the overlap is removed, and it is one of about 4 models × 3 universes × 5 horizons tried. Candidate for a forward test.

## Next steps (reference checklist)

### TiRex-2 forward test (decision pending: where it runs)

Options weighed on 2026-11-14:
- GitHub Actions + a table `vn_stock_<thing>` (automatic and durable; needs a migration, torch CPU on the runner, tests at 95%).
- A local script writing a CSV (about 30 minutes of work, no pipeline change; needs a daily manual run after a local sync).

- [ ] Decide where it runs and the universe (VN30 matches the backtest).
- [ ] Every forecast is stored **before** its outcome exists, with the time it was recorded, and never edited.
- [ ] After about 3 months (about 60 sessions, 12 non-overlapping 5-session periods): rank IC, non-overlapping t-stat, MAE vs the random walk, same metrics as above.
- [ ] Go only if the non-overlapping t-stat ≥ 2 and MAE ≤ random walk.

### Other uses worth trying later

- [ ] TiRex-2's p10–p90 band as a volatility / risk input (models of this kind forecast spread better than direction); check its coverage (share of outcomes inside the band).
- [ ] TiRex-2's 5-session median forecast as one more input of the logistic regression (step 4 of that plan), judged on the test AUC and IC like any other input.
