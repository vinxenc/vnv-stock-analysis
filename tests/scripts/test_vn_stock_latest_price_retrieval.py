import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

from libs.logger import Logger
from libs.prices import Price, PriceNotFoundError, PriceSource
from scripts import vn_stock_latest_price_retrieval as retrieval
from scripts.vn_stock_latest_price_retrieval import NO_DATA, fetch, get_prices, main, read_symbols


class FakeSource(PriceSource):
    """Pops one outcome per call: an exception to raise, or None to return a price."""

    def __init__(self, name: str, *outcomes: Exception | None) -> None:
        self.name = name
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def get_history(self, symbol: str, start: dt.date, end: dt.date) -> list[Price]:
        self.calls.append(symbol)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome:
            raise outcome
        return [
            Price.model_validate(
                dict(symbol=symbol, source=self.name, date=start, open=1, high=2, low=1, close=2, volume=10)
            )
        ]


SESSION = dt.date(2026, 10, 23)


@pytest.fixture(autouse=True)
def session_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSIONS", SESSION.isoformat())


@pytest.fixture(autouse=True)
def retry_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record tenacity's waits between attempts instead of sleeping."""
    slept: list[float] = []
    monkeypatch.setattr(fetch.retry, "sleep", slept.append)
    return slept


class FakeLogger(Logger):
    """Keeps `(level, formatted message)` pairs."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def debug(self, msg: str, *args: object) -> None:
        self.records.append(("debug", msg % args))

    def info(self, msg: str, *args: object) -> None:
        self.records.append(("info", msg % args))

    def warning(self, msg: str, *args: object) -> None:
        self.records.append(("warning", msg % args))

    def error(self, msg: str, *args: object) -> None:
        self.records.append(("error", msg % args))


def write_csv(path: Path, *codes: str) -> Path:
    path.write_text("code,short_name\n" + "".join(f"{code},Tên {code}\n" for code in codes), encoding="utf-8")
    return path


def test_read_symbols_keeps_order(tmp_path: Path) -> None:
    assert read_symbols(write_csv(tmp_path / "s.csv", "vcb", "FPT", "AAA")) == ["VCB", "FPT", "AAA"]


def test_read_symbols_dedupes_keeping_order(tmp_path: Path) -> None:
    assert read_symbols(write_csv(tmp_path / "s.csv", "VCB", "FPT", "vcb", "FPT")) == ["VCB", "FPT"]


def test_read_symbols_rejects_bad_symbol(tmp_path: Path) -> None:
    with pytest.raises(PriceNotFoundError, match="invalid symbol"):
        read_symbols(write_csv(tmp_path / "s.csv", "FPT", "F&X"))


def test_first_source_ok_no_sleep(retry_sleeps: list[float]) -> None:
    first, second = FakeSource("A"), FakeSource("B")
    assert get_prices("FPT", SESSION, SESSION, [first, second])[-1].source == "A"
    assert (len(first.calls), len(second.calls), retry_sleeps) == (1, 0, [])


def test_retries_same_source_once(retry_sleeps: list[float]) -> None:
    first, second = FakeSource("A", OSError("boom")), FakeSource("B")
    assert get_prices("FPT", SESSION, SESSION, [first, second])[-1].source == "A"
    assert (len(first.calls), len(second.calls), retry_sleeps) == (2, 0, [1])


def test_falls_back_after_two_failures() -> None:
    first, second = FakeSource("A", OSError("1"), OSError("2")), FakeSource("B")
    assert get_prices("FPT", SESSION, SESSION, [first, second])[-1].source == "B"
    assert (len(first.calls), len(second.calls)) == (2, 1)


def test_not_found_is_not_retried(retry_sleeps: list[float]) -> None:
    first, second = FakeSource("A", PriceNotFoundError("nope")), FakeSource("B")
    assert get_prices("FPT", SESSION, SESSION, [first, second])[-1].source == "B"
    assert (len(first.calls), len(second.calls), retry_sleeps) == (1, 1, [])


def test_all_sources_fail() -> None:
    sources = [FakeSource(name, OSError(f"{name}1"), OSError(f"{name}2")) for name in ("A", "B", "C")]
    with pytest.raises(RuntimeError) as error:
        get_prices("FPT", SESSION, SESSION, sources)
    assert all(f"{name}: OSError: {name}2" in str(error.value) for name in ("A", "B", "C"))
    assert sum(len(source.calls) for source in sources) == 6


def test_an_unexpected_error_in_a_source_falls_back_to_the_next() -> None:
    first, second = FakeSource("A", AttributeError("1"), AttributeError("2")), FakeSource("B")
    assert get_prices("FPT", SESSION, SESSION, [first, second])[-1].source == "B"


def test_main_skips_failed_symbol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retrieval, "MIN_COVERAGE", 0.5)  # 2 of 3 symbols
    csv_path, out = write_csv(tmp_path / "s.csv", "AAA", "BBB", "CCC"), tmp_path / "sub" / "out.json"
    first = FakeSource("A", None, PriceNotFoundError("x"), None)
    second = FakeSource("B", PriceNotFoundError("y"))
    slept: list[float] = []
    log = FakeLogger()

    assert main(csv_path, out, [first, second], sleep=slept.append, log=log) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert [entry["symbol"] for entry in data] == ["AAA", "CCC"]
    assert data[0] == {
        "symbol": "AAA", "source": "A", "unit": "thousand VND", "date": "2026-10-23",
        "open": 1.0, "high": 2.0, "low": 1.0, "close": 2.0, "volume": 10,
    }  # fmt: skip
    assert slept == [1.0, 1.0]  # n - 1 delays between symbols; not-found is not retried
    assert log.records[0] == ("info", "[1/3] AAA ok (A)")
    assert log.records[1][0] == "warning"
    assert log.records[1][1].startswith("[2/3] BBB skipped")
    assert log.records[-1] == ("info", "fetched 2, skipped 1: BBB")


def test_main_too_few_symbols_writes_nothing(tmp_path: Path) -> None:
    """A partial outage must not pass: 1 of 3 fetched is under the default 90%."""
    out = tmp_path / "out.json"
    out.write_text("[]", encoding="utf-8")  # an earlier run's file must go too
    csv_path = write_csv(tmp_path / "s.csv", "AAA", "BBB", "CCC")
    log = FakeLogger()
    source = FakeSource("A", None, PriceNotFoundError("x"), PriceNotFoundError("y"))
    assert main(csv_path, out, [source], sleep=lambda _: None, log=log) == NO_DATA
    assert log.records[-2] == (
        "warning",
        "only 1 of 3 symbols have a bar on 2026-10-23 (minimum 90%): left out, it stays due",
    )
    assert log.records[-1] == ("error", "no session from 2026-10-23 to 2026-10-23 has enough bars, nothing written")
    assert not out.exists()


def test_main_enough_symbols_is_written(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    csv_path = write_csv(tmp_path / "s.csv", *[f"A{i}" for i in range(10)])
    source = FakeSource("A", *[None] * 9, PriceNotFoundError("x"))  # 9 of 10 = exactly 90%
    assert main(csv_path, out, [source], sleep=lambda _: None) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 9


def test_main_no_data_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    csv_path = write_csv(tmp_path / "s.csv", "AAA", "BBB")
    log = FakeLogger()
    assert main(csv_path, out, [FakeSource("A", *[OSError()] * 4)], sleep=lambda _: None, log=log) == NO_DATA
    assert log.records[-1] == ("error", "no price fetched, nothing written")
    assert NO_DATA == 4  # documented in the script docstring and README
    assert not out.exists()


def test_main_no_data_removes_stale_output(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    out.write_text("[]", encoding="utf-8")
    csv_path = write_csv(tmp_path / "s.csv", "AAA")
    assert main(csv_path, out, [FakeSource("A", *[OSError()] * 2)], sleep=lambda _: None) == NO_DATA
    assert not out.exists()


def test_a_session_without_a_bar_is_not_found_and_not_retried(retry_sleeps: list[float]) -> None:
    class Empty(FakeSource):
        def get_history(self, symbol: str, start: dt.date, end: dt.date) -> list[Price]:
            self.calls.append(symbol)
            return []

    first, second = Empty("A"), FakeSource("B")
    assert get_prices("FPT", SESSION, SESSION, [first, second])[-1].source == "B"
    assert (len(first.calls), retry_sleeps) == (1, [])


def test_main_fetches_the_sessions_of_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSIONS", "2026-11-26..2026-11-27")
    out = tmp_path / "out.json"
    assert main(write_csv(tmp_path / "s.csv", "AAA"), out, [Range("A")], sleep=lambda _: None) == 0
    assert [row["date"] for row in json.loads(out.read_text(encoding="utf-8"))] == ["2026-11-26", "2026-11-27"]


class Range(FakeSource):
    """One bar per day of the span, plus one the day before it (a source that widens the span), except `missing`
    days, and except `sparse` days for the symbols after the first one."""

    def __init__(self, name: str, missing: tuple[dt.date, ...] = (), sparse: tuple[dt.date, ...] = ()) -> None:
        super().__init__(name)
        self.missing, self.sparse = missing, sparse

    def get_history(self, symbol: str, start: dt.date, end: dt.date) -> list[Price]:
        self.calls.append(symbol)
        days = [start + dt.timedelta(days=offset) for offset in range(-1, (end - start).days + 1)]
        days = [day for day in days if day not in self.missing and (symbol == "AAA" or day not in self.sparse)]
        return [
            Price.model_validate(
                dict(symbol=symbol, source=self.name, date=day, open=1, high=2, low=1, close=2, volume=10)
            )
            for day in days
        ]


def test_main_fetches_every_session_in_one_request_per_symbol(tmp_path: Path) -> None:
    out, source = tmp_path / "out.json", Range("A")
    assert main(write_csv(tmp_path / "s.csv", "AAA", "BBB"), out, [source], sleep=lambda _: None,
                sessions=(dt.date(2026, 11, 30), dt.date(2026, 12, 2))) == 0  # fmt: skip
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert [(row["symbol"], row["date"]) for row in rows] == [
        (symbol, day) for symbol in ("AAA", "BBB") for day in ("2026-11-30", "2026-12-01", "2026-12-02")
    ]  # the bar of 11-29, outside the span, is dropped
    assert source.calls == ["AAA", "BBB"]


def test_a_working_day_without_any_bar_is_passed_over(tmp_path: Path) -> None:
    """A closure the holiday calendar does not know must not stop the sync."""
    out, log = tmp_path / "out.json", FakeLogger()
    source = Range("A", missing=(dt.date(2026, 12, 1),))
    assert main(write_csv(tmp_path / "s.csv", "AAA"), out, [source], sleep=lambda _: None, log=log,
                sessions=(dt.date(2026, 11, 30), dt.date(2026, 12, 2))) == 0  # fmt: skip
    assert [row["date"] for row in json.loads(out.read_text(encoding="utf-8"))] == ["2026-11-30", "2026-12-02"]
    assert any("only 0 of 1 symbols have a bar on 2026-12-01 (minimum 90%): dropped" in m for _, m in log.records)


def test_a_session_with_too_few_bars_before_a_full_one_is_dropped(tmp_path: Path) -> None:
    """No source has the day: waiting for it would block the sync for good."""
    out, log = tmp_path / "out.json", FakeLogger()
    source = Range("A", sparse=(dt.date(2026, 12, 1),))  # 1 of 3 symbols on 12-01
    assert main(write_csv(tmp_path / "s.csv", "AAA", "BBB", "CCC"), out, [source], sleep=lambda _: None, log=log,
                sessions=(dt.date(2026, 11, 30), dt.date(2026, 12, 2))) == 0  # fmt: skip
    assert {row["date"] for row in json.loads(out.read_text(encoding="utf-8"))} == {"2026-11-30", "2026-12-02"}
    assert any("2026-12-01 (minimum 90%): dropped" in message for _, message in log.records)


def test_a_newest_session_with_too_few_bars_stays_due(tmp_path: Path) -> None:
    out, log = tmp_path / "out.json", FakeLogger()
    source = Range("A", sparse=(dt.date(2026, 12, 2),))  # not published yet for most symbols
    assert main(write_csv(tmp_path / "s.csv", "AAA", "BBB", "CCC"), out, [source], sleep=lambda _: None, log=log,
                sessions=(dt.date(2026, 11, 30), dt.date(2026, 12, 2))) == 0  # fmt: skip
    assert {row["date"] for row in json.loads(out.read_text(encoding="utf-8"))} == {"2026-11-30", "2026-12-01"}
    assert any("2026-12-02 (minimum 90%): left out, it stays due" in message for _, message in log.records)


def test_a_hole_of_the_first_source_is_filled_from_the_next_one(tmp_path: Path) -> None:
    """The span request takes A's answer as it is; the day A lacks is asked again, alone, and B has it."""
    out = tmp_path / "out.json"
    first, second = Range("A", missing=(dt.date(2026, 12, 1),)), Range("B")
    assert main(write_csv(tmp_path / "s.csv", "AAA", "BBB"), out, [first, second], sleep=lambda _: None,
                sessions=(dt.date(2026, 11, 30), dt.date(2026, 12, 2))) == 0  # fmt: skip
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert sorted((row["date"], row["source"]) for row in rows if row["date"] == "2026-12-01") == [
        ("2026-12-01", "B"),
        ("2026-12-01", "B"),
    ]
    assert len(rows) == 6 and second.calls == ["AAA", "BBB"]


def test_asking_again_stops_once_the_day_cannot_pass(tmp_path: Path) -> None:
    """A closure no calendar knows: 20 symbols, the day fails once 3 of them (over 10%) come back empty."""
    out, codes = tmp_path / "out.json", [f"S{i:02d}" for i in range(20)]
    first, second = Range("A", missing=(dt.date(2026, 12, 1),)), Range("B", missing=(dt.date(2026, 12, 1),))
    assert main(write_csv(tmp_path / "s.csv", *codes), out, [first, second], sleep=lambda _: None,
                sessions=(dt.date(2026, 11, 30), dt.date(2026, 12, 2))) == 0  # fmt: skip
    assert {row["date"] for row in json.loads(out.read_text(encoding="utf-8"))} == {"2026-11-30", "2026-12-02"}
    assert len(first.calls) == 20 + 3 and len(second.calls) == 3


def test_crash_is_not_no_data(tmp_path: Path) -> None:
    cmd = [sys.executable, "-m", "scripts.vn_stock_latest_price_retrieval", str(tmp_path / "missing.csv")]
    result = subprocess.run(cmd, capture_output=True, cwd=Path(__file__).parents[2])
    assert result.returncode == 1
    assert b"FileNotFoundError" in result.stderr
