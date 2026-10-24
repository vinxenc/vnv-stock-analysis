import json
import subprocess
import sys
from pathlib import Path

import pytest

from libs.prices import Price, PriceNotFoundError, PriceSource
from scripts.vn_stock_latest_price_retrieval import NO_DATA, get_price, main, read_symbols


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


def write_csv(path: Path, *codes: str) -> Path:
    path.write_text("code,short_name\n" + "".join(f"{c},Tên {c}\n" for c in codes), encoding="utf-8")
    return path


def test_read_symbols_keeps_order(tmp_path: Path) -> None:
    assert read_symbols(write_csv(tmp_path / "s.csv", "vcb", "FPT", "AAA")) == ["VCB", "FPT", "AAA"]


def test_read_symbols_rejects_bad_symbol(tmp_path: Path) -> None:
    with pytest.raises(PriceNotFoundError, match="invalid symbol"):
        read_symbols(write_csv(tmp_path / "s.csv", "FPT", "F&X"))


def test_first_source_ok_no_sleep() -> None:
    a, b = FakeSource("A"), FakeSource("B")
    slept: list[float] = []
    assert get_price("FPT", [a, b], sleep=slept.append).source == "A"
    assert (len(a.calls), len(b.calls), slept) == (1, 0, [])


def test_retries_same_source_once() -> None:
    a, b = FakeSource("A", OSError("boom")), FakeSource("B")
    slept: list[float] = []
    assert get_price("FPT", [a, b], retry_delay=1.5, sleep=slept.append).source == "A"
    assert (len(a.calls), len(b.calls), slept) == (2, 0, [1.5])


def test_falls_back_after_two_failures() -> None:
    a, b = FakeSource("A", OSError("1"), OSError("2")), FakeSource("B")
    assert get_price("FPT", [a, b], sleep=lambda _: None).source == "B"
    assert (len(a.calls), len(b.calls)) == (2, 1)


def test_not_found_is_not_retried() -> None:
    a, b = FakeSource("A", PriceNotFoundError("nope")), FakeSource("B")
    slept: list[float] = []
    assert get_price("FPT", [a, b], sleep=slept.append).source == "B"
    assert (len(a.calls), len(b.calls), slept) == (1, 1, [])


def test_all_sources_fail() -> None:
    sources = [FakeSource(n, OSError(f"{n}1"), OSError(f"{n}2")) for n in ("A", "B", "C")]
    with pytest.raises(RuntimeError) as e:
        get_price("FPT", sources, sleep=lambda _: None)
    assert all(f"{n}: OSError: {n}2" in str(e.value) for n in ("A", "B", "C"))
    assert sum(len(s.calls) for s in sources) == 6


def test_main_skips_failed_symbol(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path, out = write_csv(tmp_path / "s.csv", "AAA", "BBB", "CCC"), tmp_path / "sub" / "out.json"
    a = FakeSource("A", None, PriceNotFoundError("x"), None)
    b = FakeSource("B", PriceNotFoundError("y"))
    slept: list[float] = []

    assert main(csv_path, out, [a, b], delay=2.0, sleep=slept.append) == 0

    data = json.loads(out.read_text(encoding="utf-8"))
    assert [p["symbol"] for p in data] == ["AAA", "CCC"]
    assert data[0] == {
        "symbol": "AAA", "source": "A", "unit": "thousand VND", "date": "2026-10-23",
        "open": 1.0, "high": 2.0, "low": 1.0, "close": 2.0, "volume": 10,
    }  # fmt: skip
    assert slept == [2.0, 2.0]  # n - 1 delays between symbols, no retry wait (not-found is not retried)
    stdout = capsys.readouterr().out
    assert "[1/3] AAA ok (A)" in stdout
    assert "[2/3] BBB skipped" in stdout
    assert "skipped 1: BBB" in stdout


def test_main_no_data_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    csv_path = write_csv(tmp_path / "s.csv", "AAA", "BBB")
    assert main(csv_path, out, [FakeSource("A", *[OSError()] * 4)], sleep=lambda _: None) == NO_DATA
    assert NO_DATA == 4  # the workflow's `case 4)` hard-codes this value
    assert not out.exists()


def test_crash_is_not_no_data(tmp_path: Path) -> None:
    cmd = [sys.executable, "-m", "scripts.vn_stock_latest_price_retrieval", str(tmp_path / "missing.csv")]
    r = subprocess.run(cmd, capture_output=True, cwd=Path(__file__).parents[2])
    assert r.returncode == 1
    assert b"FileNotFoundError" in r.stderr
