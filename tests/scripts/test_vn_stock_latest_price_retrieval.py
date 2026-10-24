import json
import subprocess
import sys
from pathlib import Path

import pytest

from libs.logger import Logger
from libs.prices import Price, PriceNotFoundError, PriceSource
from scripts.vn_stock_latest_price_retrieval import NO_DATA, fetch, get_price, main, read_symbols


class FakeSource(PriceSource):
    """Pops one outcome per call: an exception to raise, or None to return a price."""

    def __init__(self, name: str, *outcomes: Exception | None) -> None:
        self.name = name
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def get_latest_price(self, symbol: str) -> Price:
        self.calls.append(symbol)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome:
            raise outcome
        return Price(symbol=symbol, source=self.name, date="2026-10-23", open=1, high=2, low=1, close=2, volume=10)


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
    assert get_price("FPT", [first, second]).source == "A"
    assert (len(first.calls), len(second.calls), retry_sleeps) == (1, 0, [])


def test_retries_same_source_once(retry_sleeps: list[float]) -> None:
    first, second = FakeSource("A", OSError("boom")), FakeSource("B")
    assert get_price("FPT", [first, second]).source == "A"
    assert (len(first.calls), len(second.calls), retry_sleeps) == (2, 0, [1])


def test_falls_back_after_two_failures() -> None:
    first, second = FakeSource("A", OSError("1"), OSError("2")), FakeSource("B")
    assert get_price("FPT", [first, second]).source == "B"
    assert (len(first.calls), len(second.calls)) == (2, 1)


def test_not_found_is_not_retried(retry_sleeps: list[float]) -> None:
    first, second = FakeSource("A", PriceNotFoundError("nope")), FakeSource("B")
    assert get_price("FPT", [first, second]).source == "B"
    assert (len(first.calls), len(second.calls), retry_sleeps) == (1, 1, [])


def test_all_sources_fail() -> None:
    sources = [FakeSource(name, OSError(f"{name}1"), OSError(f"{name}2")) for name in ("A", "B", "C")]
    with pytest.raises(RuntimeError) as error:
        get_price("FPT", sources)
    assert all(f"{name}: OSError: {name}2" in str(error.value) for name in ("A", "B", "C"))
    assert sum(len(source.calls) for source in sources) == 6


def test_main_skips_failed_symbol(tmp_path: Path) -> None:
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


def test_main_no_data_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    csv_path = write_csv(tmp_path / "s.csv", "AAA", "BBB")
    log = FakeLogger()
    assert main(csv_path, out, [FakeSource("A", *[OSError()] * 4)], sleep=lambda _: None, log=log) == NO_DATA
    assert log.records[-1] == ("error", "no price fetched, nothing written")
    assert NO_DATA == 4  # the workflow's `case 4)` hard-codes this value
    assert not out.exists()


def test_main_no_data_removes_stale_output(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    out.write_text("[]", encoding="utf-8")
    csv_path = write_csv(tmp_path / "s.csv", "AAA")
    assert main(csv_path, out, [FakeSource("A", *[OSError()] * 2)], sleep=lambda _: None) == NO_DATA
    assert not out.exists()


def test_crash_is_not_no_data(tmp_path: Path) -> None:
    cmd = [sys.executable, "-m", "scripts.vn_stock_latest_price_retrieval", str(tmp_path / "missing.csv")]
    result = subprocess.run(cmd, capture_output=True, cwd=Path(__file__).parents[2])
    assert result.returncode == 1
    assert b"FileNotFoundError" in result.stderr
