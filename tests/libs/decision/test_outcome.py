import datetime as dt

import pytest
from sqlalchemy import Engine, text

from libs.decision.outcome import fill_outcomes

# Eight market sessions (2026-11-07 and 08 are a weekend); MARKET trades on all of them, so they are the calendar.
S = [dt.date(2026, 11, d) for d in (2, 3, 4, 5, 6, 9, 10, 11)]


def bars(engine: Engine, symbol: str, closes: dict[dt.date, float]) -> None:
    rows = [{"symbol": symbol, "date": day, "close": close} for day, close in closes.items()]
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO vn_stock_prices (symbol, source, unit, date, open, high, low, close, volume)"
                " VALUES (:symbol, 'test', 'thousand VND', :date, :close, :close, :close, :close, 1)"
            ),
            rows,
        )


def path(*closes: float, start: int = 0) -> dict[dt.date, float]:
    """`closes` on consecutive sessions from S[start]."""
    return dict(zip(S[start:], closes, strict=False))


def decide(engine: Engine, symbol: str, day: dt.date = S[0], model: str = "fake/model") -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO vn_stock_decisions (date, symbol, model_name, decider, decision, probability, input)"
                " VALUES (:day, :symbol, :model, 'llm', 'buy', 0.6, '{}')"
            ),
            {"day": day, "symbol": symbol, "model": model},
        )


def outcomes(engine: Engine) -> list[tuple]:
    with engine.connect() as connection:
        query = "SELECT symbol, model_name, return_5, hit FROM vn_stock_decisions ORDER BY 1, 2"
        return [tuple(row) for row in connection.execute(text(query))]


def fill(engine: Engine) -> tuple[int, int]:
    with engine.begin() as connection:
        return fill_outcomes(connection)


@pytest.fixture
def market(engine: Engine) -> Engine:
    bars(engine, "MARKET", path(*[10.0] * len(S)))
    return engine


def test_a_due_decision_gets_its_outcome(market: Engine) -> None:
    bars(market, "HPG", path(20.0, 20.2, 20.4, 20.4, 20.6, 21.0, 30.0))  # S[6] is after t+5: not used
    bars(market, "FPT", path(50.0, 49.0, 48.0, 48.0, 48.5, 49.0))
    decide(market, "HPG")
    decide(market, "FPT")
    assert fill(market) == (2, 0)
    assert outcomes(market) == [("FPT", "fake/model", pytest.approx(-0.02), False), ("HPG", "fake/model", 0.05, True)]


def test_a_decision_without_its_fifth_session_waits(market: Engine) -> None:
    bars(market, "HPG", path(*[20.0] * len(S)))
    decide(market, "HPG", S[3])  # t+5 would be S[8], not stored yet
    assert fill(market) == (0, 0)  # not due: not counted as left empty
    assert outcomes(market) == [("HPG", "fake/model", None, None)]


@pytest.mark.parametrize(
    ("start", "end", "hit"),
    [(10.0, 10.3, True), (12.5, 12.875, True), (45.6, 46.968, True), (0.7, 0.721, True), (10.0, 10.2999, False)],
)
def test_exactly_three_percent_is_a_hit(market: Engine, start: float, end: float, hit: bool) -> None:
    bars(market, "HPG", path(start, start, start, start, start, end))
    decide(market, "HPG")
    fill(market)
    [(_, _, return_5, stored_hit)] = outcomes(market)
    assert stored_hit is hit
    assert (return_5 >= 0.03) is hit  # the stored return agrees with the hit


def test_a_ceiling_close_is_kept(market: Engine) -> None:
    bars(market, "HPG", path(20.0, 21.4, 22.89, 22.89, 22.89, 22.89))  # +7% twice: HOSE's band, rounded down to tick
    decide(market, "HPG")
    assert fill(market) == (1, 0)
    assert outcomes(market)[0][3] is True


def test_an_ex_rights_gap_leaves_the_outcome_empty(market: Engine) -> None:
    bars(market, "HPG", path(20.0, 20.0, 18.0, 18.0, 18.0, 18.0))  # -10% in one session: an adjustment, not a trade
    decide(market, "HPG")
    assert fill(market) == (0, 1)
    assert outcomes(market) == [("HPG", "fake/model", None, None)]


def test_a_move_before_the_session_decided_is_ignored(market: Engine) -> None:
    bars(market, "HPG", path(10.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.6))
    decide(market, "HPG", S[1])
    assert fill(market) == (1, 0)


def test_a_symbol_halted_on_its_fifth_session_keeps_an_empty_outcome(market: Engine) -> None:
    closes = path(20.0, 20.0, 20.0, 20.0, 20.0, 21.0, 21.0)
    del closes[S[5]]  # trades again on S[6]: its own fifth bar would be a later session
    bars(market, "HPG", closes)
    decide(market, "HPG")
    assert fill(market) == (0, 1)


def test_a_missing_bar_in_between_leaves_the_outcome_empty(market: Engine) -> None:
    closes = path(20.0, 20.0, 20.0, 20.0, 20.0, 21.0)
    del closes[S[2]]
    bars(market, "HPG", closes)
    decide(market, "HPG")
    assert fill(market) == (0, 1)


def test_every_model_of_a_symbol_gets_the_outcome(market: Engine) -> None:
    bars(market, "HPG", path(20.0, 20.0, 20.0, 20.0, 20.0, 21.0))
    decide(market, "HPG", model="a/one")
    decide(market, "HPG", model="b/two")
    assert fill(market) == (2, 0)
    assert outcomes(market) == [("HPG", "a/one", 0.05, True), ("HPG", "b/two", 0.05, True)]


def test_a_second_run_changes_nothing(market: Engine) -> None:
    bars(market, "HPG", path(20.0, 20.0, 20.0, 20.0, 20.0, 21.0))
    bars(market, "FPT", path(50.0, 40.0, 40.0, 40.0, 40.0, 40.0))  # left empty for good
    decide(market, "HPG")
    decide(market, "FPT")
    assert fill(market) == (1, 1)
    table = outcomes(market)
    assert fill(market) == (0, 1)  # the filled row is not touched again; the empty one is due and still empty
    assert outcomes(market) == table


def test_a_row_answered_again_is_filled_again(market: Engine) -> None:
    bars(market, "HPG", path(20.0, 20.0, 20.0, 20.0, 20.0, 21.0))
    decide(market, "HPG")
    fill(market)
    with market.begin() as connection:  # what the deciders' upsert does to a symbol answered again
        connection.execute(text("UPDATE vn_stock_decisions SET hit = NULL, return_5 = NULL"))
    assert fill(market) == (1, 0)
    assert outcomes(market) == [("HPG", "fake/model", 0.05, True)]


def test_no_decision_does_nothing(market: Engine) -> None:
    assert fill(market) == (0, 0)
