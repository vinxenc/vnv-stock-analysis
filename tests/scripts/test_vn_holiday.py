import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.vn_holiday import WORKING_DAY, off_reason

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(("arg", "code"), [("2026-11-24", 0), ("2026-10-23", WORKING_DAY), ("not-a-date", 1)])
def test_exit_code(arg: str, code: int) -> None:
    # a crash (bad date) must not exit with the working-day code
    cmd = [sys.executable, "-m", "scripts.vn_holiday", arg]
    assert subprocess.run(cmd, capture_output=True, cwd=ROOT).returncode == code


@pytest.mark.parametrize(
    ("d", "off"),
    [
        (date(2026, 10, 23), False),  # Fri, normal day
        (date(2026, 10, 24), True),  # Sat
        (date(2026, 2, 17), True),  # Tết (lunar)
        (date(2026, 4, 27), True),  # Giỗ Tổ nghỉ bù (26/4 is a Sunday)
        (date(2026, 8, 31), True),  # swap day for 22/8
        (date(2026, 9, 2), True),  # Quốc khánh
        (date(2026, 11, 24), True),  # Ngày Văn hóa Việt Nam
    ],
)
def test_off_reason(d: date, off: bool) -> None:
    assert (off_reason(d) is not None) is off


# Every 2027 public holiday that falls on a weekday (weekends are covered by the weekday check)
HOLIDAYS_2027 = [
    date(2027, 1, 1),  # Tết Dương lịch
    date(2027, 2, 4),  # 29 Tết
    date(2027, 2, 5),  # Giao thừa
    date(2027, 2, 8),  # Mùng ba
    date(2027, 2, 9),  # Mùng bốn
    date(2027, 2, 10),  # Mùng năm
    date(2027, 4, 16),  # Giỗ Tổ Hùng Vương (10/3 âm lịch)
    date(2027, 4, 30),  # Ngày Chiến thắng
    date(2027, 5, 3),  # Quốc tế Lao động nghỉ bù (1/5 is a Saturday)
    date(2027, 9, 2),  # Quốc khánh
    date(2027, 9, 3),  # Quốc khánh
    date(2027, 11, 24),  # Ngày Văn hóa Việt Nam
]


@pytest.mark.parametrize("d", HOLIDAYS_2027)
def test_holidays_2027(d: date) -> None:
    assert d.weekday() < 5
    assert off_reason(d) not in (None, "weekend")


def test_no_other_weekday_holidays_2027() -> None:
    days = (date(2027, 1, 1) + timedelta(n) for n in range(365))
    assert [d for d in days if d.weekday() < 5 and off_reason(d)] == HOLIDAYS_2027
