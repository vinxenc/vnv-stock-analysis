import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.pipeline_state import main, resolve


def test_success_uses_given_level_and_message() -> None:
    state = resolve("retrieve", "success", "info", "ok", "bad")
    assert state == {"level": "info", "message": "ok", "pipeline": "retrieve"}
    assert resolve("is_holiday", "success", "warning", "day off", "bad")["level"] == "warning"


def test_failure_is_error_with_failure_message() -> None:
    state = resolve("retrieve", "failure", "info", "ok", "bad")
    assert state == {"level": "error", "message": "bad", "pipeline": "retrieve"}


def test_cancelled_is_warning() -> None:
    assert resolve("retrieve", "cancelled", "info", "ok", "bad") == {
        "level": "warning",
        "message": "retrieve was cancelled",
        "pipeline": "retrieve",
    }


def test_unknown_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="level must be one of"):
        resolve("retrieve", "success", "fatal", "ok", "bad")


def test_main_writes_json_file(tmp_path: Path) -> None:
    assert main([str(tmp_path / "state"), "retrieve", "success", "info", "ok", "bad"]) == 0
    data = json.loads((tmp_path / "state" / "retrieve.json").read_text(encoding="utf-8"))
    assert data == {"level": "info", "message": "ok", "pipeline": "retrieve"}


def test_run_as_script(tmp_path: Path) -> None:
    """The workflow calls it with the system python3, from the repo root."""
    args = [str(tmp_path), "install", "failure", "info", "ok", "install failed"]
    cmd = [sys.executable, "scripts/pipeline_state.py", *args]
    assert subprocess.run(cmd, capture_output=True, cwd=Path(__file__).parents[2]).returncode == 0
    assert json.loads((tmp_path / "install.json").read_text(encoding="utf-8"))["level"] == "error"
