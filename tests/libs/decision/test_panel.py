import datetime as dt
import math

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from libs.analysis.models import IndicatorStatus
from libs.analysis.report import build_report
from libs.constants import HISTORY_SESSIONS
from libs.decision import panel
from libs.decision.outcome import fill_outcomes, outcome
from libs.indicators import TalibIndicators
from scripts.vn_stock_analyze import store
from scripts.vn_stock_get_history import get_history
from scripts.vn_stock_screen import screen

ENGINE = TalibIndicators()
FIRST = dt.date(2025, 1, 1)


def every_day(day: dt.date) -> bool:
    return True


def seed(engine: Engine, symbol: str, count: int, volume: int = 3_000_000, phase: float = 0.0) -> list[dt.date]:
    """`count` daily bars from FIRST, a wavy price around 10 (thousand VND): 3,000,000 shares make 30 billion VND."""
    rows = []
    for n in range(count):
        close = round(10 + 2 * math.sin(n / 7 + phase) + n / 100, 2)
        day = FIRST + dt.timedelta(days=n)
        high, low = close * 1.01, close * 0.99
        rows.append({"symbol": symbol, "date": day, "o": close, "h": high, "l": low, "c": close, "v": volume + n})
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO vn_stock_prices (symbol, source, unit, date, open, high, low, close, volume)"
                " VALUES (:symbol, 'test', 'thousand VND', :date, :o, :h, :l, :c, :v)"
            ),
            rows,
        )
    return [row["date"] for row in rows]


def build(engine: Engine, start: dt.date = FIRST, end: dt.date = dt.date(2030, 1, 1)) -> list[dict]:
    return panel.build_panel(engine, start, end, every_day, ENGINE)


def at(rows: list[dict], day: dt.date) -> dict[str, dict]:
    return {row["symbol"]: row for row in rows if row["date"] == day}


def test_the_panel_has_21_inputs() -> None:
    assert len(panel.INPUTS) == 21
    assert "close_vs_sma200" not in panel.INPUTS.values() and "close_vs_250_high" not in panel.INPUTS.values()


def test_a_row_equals_the_live_run(engine: Engine) -> None:
    """The live path (screen, then the last 260 bars, then build_report) and the panel agree on t."""
    days = seed(engine, "AAA", 300)
    seed(engine, "BBB", 300, phase=1.0)
    seed(engine, "CCC", 300, phase=2.0)
    seed(engine, "TINY", 300, volume=10)  # far below MIN_TURNOVER
    t = days[-10]
    live = screen(engine, t)
    with Session(engine) as session:
        history = {symbol: get_history(session, symbol, t) for symbol in live}
    assert all(len(rows) == HISTORY_SESSIONS for rows in history.values())  # the window is cut, not all 291 bars
    report = build_report(history, dict.fromkeys(live, dt.date.min), ENGINE)
    rows = at(build(engine), t)
    assert sorted(rows) == live == ["AAA", "BBB", "CCC"]
    for result in report.symbols:
        row = rows[result.symbol]
        assert row["score"] == result.score and row["turnover"] == pytest.approx(result.turnover)
        for indicator in result.indicators:
            name = panel.INPUTS.get(indicator.id)
            if name and indicator.status == IndicatorStatus.SCORED:
                assert row[name] == pytest.approx(indicator.raw[name]), name


def test_no_bar_after_t_changes_the_inputs(engine: Engine) -> None:
    days = seed(engine, "AAA", 120)
    t = days[100]
    before = at(build(engine), t)["AAA"]
    with engine.begin() as connection:
        connection.execute(text("UPDATE vn_stock_prices SET close = close * 1.05 WHERE date > :t"), {"t": t})
    after = at(build(engine), t)["AAA"]
    assert {k: v for k, v in after.items() if k not in panel.LABELS} == {
        k: v for k, v in before.items() if k not in panel.LABELS
    }
    assert after["fwd_return_5"] != before["fwd_return_5"]


def test_the_universe_is_the_screens(engine: Engine) -> None:
    days = seed(engine, "AAA", 60)
    seed(engine, "TINY", 60, volume=10)
    seed(engine, "HALT", 59)  # no bar on the last day
    with engine.begin() as connection:  # traded nothing on day 30
        connection.execute(
            text("UPDATE vn_stock_prices SET volume = 0 WHERE symbol = 'AAA' AND date = :d"), {"d": days[30]}
        )
    rows = build(engine)
    assert sorted(at(rows, days[-1])) == ["AAA"]
    assert sorted(at(rows, days[30])) == ["HALT"]  # TINY never: 10 x ~10 thousand VND is far below MIN_TURNOVER


def test_labels(engine: Engine) -> None:
    days = seed(engine, "AAA", 80)
    seed(engine, "BBB", 80, phase=3.0)
    rows = build(engine, start=days[70])
    assert {row["date"] for row in rows} == set(days[70:])
    for row in rows:
        if row["date"] > days[-6]:  # t+5 not stored yet
            assert all(row[label] is None for label in panel.LABELS)
        else:
            assert row["fwd_return_5"] is not None and row["hit_3pct_5"] == int(row["fwd_return_5"] >= 0.03)
    t = at(rows, days[70])
    a, b = t["AAA"]["fwd_return_5"], t["BBB"]["fwd_return_5"]
    assert t["AAA"]["excess_return_5"] == pytest.approx((a - b) / 2)
    assert t["AAA"]["beat_median"] + t["BBB"]["beat_median"] == 1


def test_an_empty_session_is_skipped(engine: Engine) -> None:
    seed(engine, "TINY", 30, volume=10)
    assert build(engine) == []


# The Python label of the panel equals the SQL label of the decisions on every rule of `_FILL` (test_outcome.py).
S = [dt.date(2026, 11, d) for d in (2, 3, 4, 5, 6, 9, 10, 11)]


def path(*closes: float | None) -> dict[dt.date, float]:
    """`closes` on consecutive sessions from S[0]; None = no bar that session."""
    return {day: close for day, close in zip(S, closes, strict=False) if close is not None}


SCENARIOS = {
    "hit": ({"X": path(20.0, 20.2, 20.4, 20.4, 20.6, 21.0, 30.0)}, ()),
    "miss": ({"X": path(50.0, 49.0, 48.0, 48.0, 48.5, 49.0)}, ()),
    **{
        f"exact {start}": ({"X": path(start, start, start, start, start, end)}, ())
        for start, end in [(10.0, 10.3), (12.5, 12.875), (45.6, 46.968), (0.7, 0.721), (10.0, 10.2999)]
    },
    "ceiling kept": ({"X": path(10.0, 10.7, 10.7, 10.7, 10.7, 10.7)}, ()),
    "gap left empty": ({"X": path(10.0, 11.0, 11.0, 11.0, 11.0, 11.0)}, ()),
    "missing bar": ({"X": path(10.0, 10.0, None, 10.0, 10.0, 10.5)}, ()),
    "halted on t+5": ({"X": path(10.0, 10.0, 10.0, 10.0, 10.0, None, 10.5)}, ()),
    "t+5 not stored": ({"X": path(10.0, 10.0, 10.0, 10.0)}, ()),
}


def without(day: dt.date, closes: dict[dt.date, float]) -> dict[dt.date, float]:
    return {d: c for d, c in closes.items() if d != day}


@pytest.mark.parametrize(
    ("bars", "days_off"),
    [
        *SCENARIOS.values(),
        # a session the sync missed for every symbol: stored dates skip it, the calendar does not
        ({"X": without(S[3], path(*[10.0] * 8)), "M": without(S[3], path(*[1.0] * 8))}, ()),
        # a holiday: missing from the stored dates and off in the calendar
        ({"X": without(S[3], path(10.0, 10, 10, 10, 10, 10, 10.4)), "M": without(S[3], path(*[1.0] * 8))}, (S[3],)),
    ],
    ids=[*SCENARIOS, "session missed", "holiday"],
)
def test_the_python_label_equals_the_sql_one(
    engine: Engine, bars: dict[str, dict[dt.date, float]], days_off: tuple[dt.date, ...]
) -> None:
    def is_working_day(day: dt.date) -> bool:
        return day.weekday() < 5 and day not in days_off

    market = bars if "M" in bars else {**bars, "M": path(*[1.0] * len(S))}  # M trades every stored session
    rows = [
        {"symbol": symbol, "date": day, "close": close}
        for symbol, closes in market.items()
        for day, close in closes.items()
    ]
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO vn_stock_prices (symbol, source, unit, date, open, high, low, close, volume)"
                " VALUES (:symbol, 'test', 'thousand VND', :date, :close, :close, :close, :close, 1)"
            ),
            rows,
        )
        connection.execute(
            text(
                "INSERT INTO vn_stock_decisions (date, symbol, model_name, decider, decision, probability, input)"
                " VALUES (:day, 'X', 'fake/model', 'llm', 'buy', 0.6, '{}')"
            ),
            {"day": S[0]},
        )
        fill_outcomes(connection, is_working_day)
        stored = connection.execute(text("SELECT return_5, hit FROM vn_stock_decisions")).one()
    sessions = sorted({day for closes in market.values() for day in closes})
    python = outcome(sessions, 0, market["X"], is_working_day)
    if stored.hit is None:
        assert python is None
    else:
        assert python == (pytest.approx(stored.return_5), stored.hit)


def test_the_lookahead_check(engine: Engine) -> None:
    days = seed(engine, "AAA", 300)
    seed(engine, "BBB", 300, phase=1.0)
    assert panel.lookahead_check(engine, ENGINE) == (0, [])  # nothing stored: nothing proven
    for t in days[-3:]:
        with Session(engine) as session:
            history = {symbol: get_history(session, symbol, t) for symbol in screen(engine, t)}
        store(build_report(history, dict.fromkeys(history, dt.date.min), ENGINE), engine)
    assert panel.lookahead_check(engine, ENGINE) == (3, [])

    def edit(sql: str) -> list[str]:
        with engine.begin() as connection:
            connection.execute(text(sql), {"t": days[-1]})
        return panel.lookahead_check(engine, ENGINE)[1]

    # #12 (the 12th element) in its form before #33: the gated value, no `up_day`
    old_form = (
        "UPDATE vn_stock_rankings SET indicators = jsonb_set(indicators, '{11,raw}', jsonb_build_object("
        "'volume_vs_average', CASE WHEN (indicators->11->'raw'->>'up_day')::float = 1"
        " THEN indicators->11->'raw'->'volume_vs_average' ELSE '0'::jsonb END)) WHERE date = :t"
    )
    assert edit(old_form) == []
    wrong = edit(
        "UPDATE vn_stock_rankings SET indicators = jsonb_set(indicators, '{11,raw,volume_vs_average}', '99')"
        " WHERE date = :t AND symbol = 'AAA'"
    )
    assert len(wrong) == 1 and "AAA #12" in wrong[0]
    extra = edit(
        "UPDATE vn_stock_rankings SET indicators = jsonb_set(indicators, '{0,raw,extra}', '\"x\"')"
        " WHERE date = :t AND symbol = 'BBB'"
    )
    assert len(extra) == 2 and any("BBB #1" in line for line in extra)
    gone = edit("UPDATE vn_stock_prices SET volume = 0 WHERE symbol = 'BBB' AND date = :t")
    assert any("BBB: stored, but not in the replayed universe" in line for line in gone)
