import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from libs.db.models import Price
from libs.prices import PriceNotFoundError, PriceSource
from scripts.vn_stock_daily_price_store import store
from scripts.vn_stock_dividend_history import fetch, main

TODAY = dt.date(2021, 6, 15)


def bar(symbol: str, day: dt.date, close: float, source: str = "DNSE") -> Price:
    return Price.model_validate(
        dict(symbol=symbol, source=source, date=day, open=close, high=close, low=close, close=close, volume=100)
    )


class FakeSource(PriceSource):
    """One adjusted bar per year asked for (a year before `listed` has none), or `error` for the year `fails`."""

    def __init__(self, name: str, fails: int | None = None, listed: int = 2019) -> None:
        self.name, self.fails, self.listed = name, fails, listed
        self.calls: list[tuple[str, dt.date, dt.date]] = []

    def get_latest_price(self, symbol: str) -> Price:
        raise AssertionError("not used")

    def get_history(self, symbol: str, start: dt.date, end: dt.date) -> list[Price]:
        self.calls.append((symbol, start, end))
        if start.year == self.fails:
            raise ConnectionError("down")
        return [bar(symbol, end, 9.0, self.name)] if start.year >= self.listed else []


class FakeCalendar:
    def __init__(self, *symbols: str) -> None:
        self.symbols = set(symbols)
        self.days: list[dt.date] = []

    def get_ex_rights(self, day: dt.date) -> set[str]:
        self.days.append(day)
        return self.symbols


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch.retry, "sleep", lambda seconds: None)


@pytest.fixture
def symbols_csv(tmp_path: Path) -> Path:
    path = tmp_path / "symbols.csv"
    path.write_text("code\nFPT\nVPX\n", encoding="utf-8")
    return path


def stored(engine: Engine) -> list[tuple[str, str, float, str]]:
    with Session(engine) as session:
        rows = session.exec(select(Price).order_by(Price.symbol, Price.date))
        return [(row.symbol, str(row.date), row.close, row.source) for row in rows]


def run(symbols_csv: Path, engine: Engine | None, *sources: PriceSource, calendar: FakeCalendar) -> int:
    return main(symbols_csv, engine, TODAY, sources, calendar, delay=0, sleep=lambda seconds: None)


def test_no_ex_rights_today_touches_nothing(symbols_csv: Path) -> None:
    calendar = FakeCalendar("ABI")  # not listed on HOSE
    assert run(symbols_csv, None, FakeSource("DNSE"), calendar=calendar) == 0  # no engine needed
    assert calendar.days == [TODAY]


def test_the_history_is_re_stored_one_request_per_year(symbols_csv: Path, engine: Engine) -> None:
    """The raw stored bar of 2020 takes the source's adjusted value, the other years are added."""
    store([bar("FPT", dt.date(2020, 12, 31), 10.0), bar("VPX", dt.date(2020, 12, 31), 5.0)], engine)
    dnse = FakeSource("DNSE")
    assert run(symbols_csv, engine, dnse, calendar=FakeCalendar("FPT")) == 0
    assert dnse.calls == [
        ("FPT", dt.date(2019, 1, 1), dt.date(2019, 12, 31)),
        ("FPT", dt.date(2020, 1, 1), dt.date(2020, 12, 31)),
        ("FPT", dt.date(2021, 1, 1), TODAY),
    ]
    assert stored(engine) == [
        ("FPT", "2019-12-31", 9.0, "DNSE"),
        ("FPT", "2020-12-31", 9.0, "DNSE"),
        ("FPT", "2021-06-15", 9.0, "DNSE"),
        ("VPX", "2020-12-31", 5.0, "DNSE"),  # no ex-rights date today: untouched
    ]


def test_a_symbol_listed_later_has_no_bar_for_the_early_years(symbols_csv: Path, engine: Engine) -> None:
    assert run(symbols_csv, engine, FakeSource("DNSE", listed=2021), calendar=FakeCalendar("FPT")) == 0
    assert stored(engine) == [("FPT", "2021-06-15", 9.0, "DNSE")]


def test_one_failing_year_takes_the_whole_history_from_the_next_source(symbols_csv: Path, engine: Engine) -> None:
    dnse, vps = FakeSource("DNSE", fails=2020), FakeSource("VPS")
    assert run(symbols_csv, engine, dnse, vps, calendar=FakeCalendar("FPT")) == 0
    assert {row[3] for row in stored(engine)} == {"VPS"} and len(vps.calls) == 3
    assert len(dnse.calls) == 3  # 2019, then 2020 twice (one retry)


def test_a_symbol_no_source_can_fetch_crashes_and_stores_nothing(symbols_csv: Path, engine: Engine) -> None:
    with pytest.raises(RuntimeError, match="FPT: all sources failed"):
        run(
            symbols_csv,
            engine,
            FakeSource("DNSE", fails=2019),
            FakeSource("VPS", listed=2030),
            calendar=FakeCalendar("FPT"),
        )
    assert stored(engine) == []


def test_an_unknown_ticker_is_not_retried(symbols_csv: Path, engine: Engine) -> None:
    class Unknown(FakeSource):
        def get_history(self, symbol: str, start: dt.date, end: dt.date) -> list[Price]:
            self.calls.append((symbol, start, end))
            raise PriceNotFoundError("no data")

    source = Unknown("DNSE")
    with pytest.raises(RuntimeError, match="PriceNotFoundError"):
        run(symbols_csv, engine, source, calendar=FakeCalendar("FPT"))
    assert len(source.calls) == 1
