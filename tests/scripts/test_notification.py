import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.notification import main


def write_state(directory: Path, pipeline: str, level: str, message: str) -> None:
    (directory / f"{pipeline}.json").write_text(
        json.dumps({"level": level, "message": message, "pipeline": pipeline}), encoding="utf-8"
    )


def test_each_level_becomes_its_annotation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_state(tmp_path, "a_install", "info", "installed")
    write_state(tmp_path, "b_holiday", "warning", "Today is Holiday")
    write_state(tmp_path, "c_retrieve", "error", "Pipeline failed")
    assert main(tmp_path) == 0
    assert capsys.readouterr().out.splitlines() == [
        "::notice title=a_install::installed",
        "::warning title=b_holiday::Today is Holiday",
        "::error title=c_retrieve::Pipeline failed",
    ]


def test_message_with_percent_is_logged_literally(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_state(tmp_path, "a:b", "info", "100% done\nnext")
    assert main(tmp_path) == 0
    assert capsys.readouterr().out == "::notice title=a%3Ab::100%25 done%0Anext\n"


def test_no_state_files_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(tmp_path) == 0
    assert capsys.readouterr().out.startswith("::warning title=notification::no pipeline state found")


@pytest.mark.parametrize("content", ["not json", '{"level": "fatal", "message": "x", "pipeline": "p"}', "[]"])
def test_unreadable_state_is_an_error_and_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    (tmp_path / "bad.json").write_text(content, encoding="utf-8")
    write_state(tmp_path, "good", "info", "fine")
    assert main(tmp_path) == 1
    out = capsys.readouterr().out
    assert "::error title=bad.json::unreadable pipeline state" in out
    assert "::notice title=good::fine" in out  # one bad file does not hide the others


def test_job_without_state_falls_back_to_its_result(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_state(tmp_path, "install", "info", "ok")
    results = {"install": "failure", "checkout": "failure", "hung": "cancelled", "later": "skipped"}
    needs = {name: {"result": result, "outputs": {}} for name, result in results.items()}
    assert main(tmp_path, json.dumps(needs)) == 0
    assert capsys.readouterr().out.splitlines() == [
        "::notice title=install::ok",  # its own state wins over the job result
        "::error title=checkout::checkout failed before it could write its state, see the job log",
        "::warning title=hung::hung was cancelled before it could write its state",
    ]  # a skipped job says nothing


def test_run_as_script(tmp_path: Path) -> None:
    write_state(tmp_path, "install", "info", "ok")
    env = {**os.environ, "NEEDS": '{"checkout": {"result": "failure"}}'}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.notification", str(tmp_path)],
        capture_output=True, text=True, cwd=Path(__file__).parents[2], env=env,
    )  # fmt: skip
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == "::notice title=install::ok"
    assert result.stdout.splitlines()[1].startswith("::error title=checkout::checkout failed")
