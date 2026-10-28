"""Log every pipeline state file as a coloured GitHub Actions annotation.

Usage: [NEEDS='<toJSON(needs)>'] uv run python -m scripts.notification [state_directory]      (default: state)
Reads `*.json` files of {"level": "info"|"warning"|"error", "message": ..., "pipeline": ...} (written by
scripts/pipeline_state.py) and logs each one through a GithubActionsLogger titled with the pipeline name:
info -> ::notice, warning -> ::warning, error -> ::error.
$NEEDS (the workflow's `toJSON(needs)`) is the fallback for a job that died before it could write its file (failed
checkout, runner lost): a failed job without a state file is logged as an error, a cancelled one as a warning.
A file that cannot be read or has an unknown level is logged as an error and makes the exit code 1.
"""
import json
import os
import sys
from pathlib import Path

from libs.logger import GithubActionsLogger

LEVELS = ("info", "warning", "error")  # also the Logger method names
NO_STATE = {  # job result -> (level, what happened)
    "failure": ("error", "failed before it could write its state, see the job log"),
    "cancelled": ("warning", "was cancelled before it could write its state"),
}


def log(title: str, level: str, message: str) -> None:
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}")
    getattr(GithubActionsLogger(title), level)("%s", message)


def main(directory: Path = Path("state"), needs_json: str = "{}") -> int:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        log("notification", "warning", f"no pipeline state found in {directory}")
    failed = False
    for path in paths:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            log(str(state["pipeline"]), state["level"], str(state["message"]))
        except (OSError, ValueError, KeyError, TypeError) as error:
            failed = True
            log(path.name, "error", f"unreadable pipeline state: {type(error).__name__}: {error}")
    reported = {path.stem for path in paths}
    for job, need in json.loads(needs_json).items():
        if job not in reported and need["result"] in NO_STATE:
            level, what = NO_STATE[need["result"]]
            log(job, level, f"{job} {what}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state"), os.environ.get("NEEDS", "{}")))
