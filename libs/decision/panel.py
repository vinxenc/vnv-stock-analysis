"""The feature panel of Phase 3 (docs/plans/phase-3-logistic-regression-score.md, step 1), also TabICL's context.

Replays the live run on every past session t: the screen's universe (`MIN_TURNOVER` over `TURNOVER_SESSIONS` rows, a
traded bar on t), then the scoring of `libs/analysis` on each symbol's last `HISTORY_SESSIONS` bars up to t, the same
window `vn_stock_get_history` gives the live run (RSI and PPO are recursive, so a longer window would change them).
One row per (date, symbol): the 21 raw inputs, the 0-100 `score` and the forward labels of `libs/decision/outcome.py`.
Main dependencies only (CI tests it without the `research` group): plain dicts, no pandas.
"""

import datetime as dt
import math
from bisect import bisect_right
from collections.abc import Callable
from statistics import median

from sqlalchemy import Engine
from sqlmodel import Session, select

from libs.analysis import scoring
from libs.analysis.features import Candles, Detection, mean
from libs.analysis.models import IndicatorResult
from libs.analysis.report import symbol_result
from libs.constants import HISTORY_SESSIONS, MIN_TURNOVER, TURNOVER_SESSIONS
from libs.db.models import Price, Ranking
from libs.decision.outcome import outcome
from libs.indicators import Indicators

DROPPED = (5, 17, 19)  # Option B: #5 and #17 need 200 and 250 rows; #19 is #1's raw value again
INPUTS = {indicator.id: indicator.raw_name for indicator in scoring.INDICATORS if indicator.id not in DROPPED}
LABELS = ("fwd_return_5", "excess_return_5", "beat_median", "hit_3pct_5")
UP_DAY_SINCE = "up_day"  # #12 stores this key since #33 (2026-11-16); older rows hold the gated value instead
REL_TOL, ABS_TOL = 1e-6, 1e-9  # the windows are the same, so only float noise is allowed

Prices = dict[str, list[Price]]  # symbol -> every stored row, ascending by date
Replayed = dict[str, tuple[dict[int, scoring.Raw], list[IndicatorResult], float, float | None]]


def load_prices(engine: Engine) -> Prices:
    """Every row of `vn_stock_prices` (about 170,000), grouped by symbol."""
    prices: Prices = {}
    with Session(engine) as session:
        for row in session.exec(select(Price).order_by(Price.symbol, Price.date)):
            prices.setdefault(row.symbol, []).append(row)
    return prices


def _window(rows: list[Price], dates: list[dt.date], t: dt.date) -> list[Price]:
    """The last HISTORY_SESSIONS rows up to t, as `vn_stock_get_history.get_history` reads them."""
    end = bisect_right(dates, t)
    return rows[max(0, end - HISTORY_SESSIONS) : end]


def replay(prices: Prices, dates: dict[str, list[dt.date]], t: dt.date, engine: Indicators) -> Replayed:
    """What the live run would have scored on t: per symbol of the universe, its raw values, its indicator results (the
    stored `indicators`), its turnover and its score."""
    history = {}
    for symbol, rows in prices.items():
        window = _window(rows, dates[symbol], t)
        recent = window[-TURNOVER_SESSIONS:]
        if window and window[-1].date == t and window[-1].volume > 0:  # traded on t
            if mean([row.close * row.volume for row in recent]) >= MIN_TURNOVER:
                history[symbol] = Candles.from_prices(window)
    raws = {symbol: scoring.raw_values(candles, engine) for symbol, candles in history.items()}
    ranks = scoring.percentile_ranks(raws)
    result = {}
    for symbol, candles in history.items():
        indicators = scoring.score_indicators(raws[symbol], ranks[symbol])
        scored = symbol_result(symbol, candles, indicators, dt.date.min, t)  # the listing date only sets a flag
        result[symbol] = (raws[symbol], indicators, scored.turnover, scored.score)
    return result


def _input(raw: scoring.Raw, name: str) -> float | None:
    """The raw value as a number. A shape (#22-#24) gives its strength even when the uptrend gate blocks its points;
    #12 gives the real volume ratio (its detail of that name), not the strength gated on up days."""
    return float(raw.details.get(name, raw.strength)) if isinstance(raw, Detection) else raw  # type: ignore[arg-type]


def build_panel(
    engine: Engine,
    start: dt.date,
    end: dt.date,
    is_working_day: Callable[[dt.date], bool],
    indicators: Indicators,
    prices: Prices | None = None,
) -> list[dict]:
    """One row per (date, symbol) of the universe, for every stored session in [start, end]. A cell is None when it
    cannot be computed; the labels are None until t+5 is stored (and wherever `outcome` leaves them empty)."""
    prices = prices if prices is not None else load_prices(engine)
    dates = {symbol: [row.date for row in rows] for symbol, rows in prices.items()}
    closes = {symbol: {row.date: row.close for row in rows} for symbol, rows in prices.items()}
    sessions = sorted({day for days in dates.values() for day in days})
    panel = []
    for index, t in enumerate(sessions):
        if not start <= t <= end:
            continue
        rows = []
        for symbol, (raws, _, turnover, score) in replay(prices, dates, t, indicators).items():
            labelled = outcome(sessions, index, closes[symbol], is_working_day)
            rows.append(
                {
                    "date": t,
                    "symbol": symbol,
                    "turnover": turnover,
                    **{name: _input(raws[id_], name) for id_, name in INPUTS.items()},
                    "score": score,
                    "fwd_return_5": None if labelled is None else labelled[0],
                    "hit_3pct_5": None if labelled is None else int(labelled[1]),
                }
            )
        known = [row["fwd_return_5"] for row in rows if row["fwd_return_5"] is not None]
        middle = median(known) if known else None
        for row in rows:
            forward = row["fwd_return_5"]
            row["excess_return_5"] = None if forward is None else forward - middle
            row["beat_median"] = None if forward is None else int(forward > middle)
        panel.extend(rows)
    return panel


def _expected(stored: dict, replayed: dict) -> dict:
    """The replayed facts in the stored form: a #12 row stored before #33 holds the gated strength (0 off up days)."""
    if "volume_vs_average" in stored and UP_DAY_SINCE not in stored and UP_DAY_SINCE in replayed:
        gated = replayed["volume_vs_average"] if replayed[UP_DAY_SINCE] else 0.0
        return {**{k: v for k, v in replayed.items() if k != UP_DAY_SINCE}, "volume_vs_average": gated}
    return replayed


def _same(stored: dict, expected: dict) -> bool:
    if stored.keys() != expected.keys():
        return False
    for key, value in stored.items():
        other = expected[key]
        if isinstance(value, int | float) and isinstance(other, int | float):
            if not math.isclose(value, other, rel_tol=REL_TOL, abs_tol=ABS_TOL):
                return False
        elif value != other:
            return False
    return True


def lookahead_check(engine: Engine, indicators: Indicators, prices: Prices | None = None) -> tuple[int, list[str]]:
    """Replay every session of `vn_stock_rankings` and compare each stored indicator's `raw` with the replayed one.
    Returns (sessions compared, mismatches as readable lines). Zero sessions compared proves nothing. `prices`: what
    `load_prices` returned, to read the table once."""
    with Session(engine) as session:
        stored = session.exec(select(Ranking.date, Ranking.symbol, Ranking.indicators).order_by(Ranking.date)).all()
    prices = prices if prices is not None else load_prices(engine)
    dates = {symbol: [row.date for row in rows] for symbol, rows in prices.items()}
    mismatches: list[str] = []
    by_session: dict[dt.date, list[tuple[str, list[dict]]]] = {}
    for day, symbol, items in stored:
        by_session.setdefault(day, []).append((symbol, items))
    for day, symbols in by_session.items():
        replayed = replay(prices, dates, day, indicators)
        for symbol, items in symbols:
            if symbol not in replayed:
                mismatches.append(f"{day} {symbol}: stored, but not in the replayed universe")
                continue
            again = {result.id: result.raw for result in replayed[symbol][1]}
            for item in items:
                expected = _expected(item["raw"], again[item["id"]])
                if not _same(item["raw"], expected):
                    mismatches.append(f"{day} {symbol} #{item['id']}: stored {item['raw']}, replayed {expected}")
    return len(by_session), mismatches
