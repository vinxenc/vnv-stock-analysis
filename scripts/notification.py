"""Log every pipeline state file as a coloured GitHub Actions annotation.

Usage: [NEEDS='<toJSON(needs)>'] python3 -m scripts.notification [state_directory]      (default: state)
Reads `*.json` files of {"level": "info"|"warning"|"error", "message": ..., "pipeline": ...} (written by
scripts/pipeline_state.py) and logs each one through a GithubActionsLogger titled with the pipeline name:
info -> ::notice, warning -> ::warning, error -> ::error.
$NEEDS (the workflow's `toJSON(needs)`) is the fallback for a job whose final result its state file does not report:
it died before writing the file (failed checkout, runner lost) or after it (a post step failed, a late cancel). A
failed job is logged as an error unless its state is already `error`; a cancelled one as a warning unless its state
is already `warning` or `error`.
Standard library plus libs.logger.GithubActionsLogger only: it must run even when `uv sync` failed.
A file that cannot be read or has an unknown level is logged as an error and makes the exit code 1.
"""

import json
import os
import sys
from pathlib import Path

from libs.logger import GithubActionsLogger

LEVELS = ("info", "warning", "error")  # also the Logger method names
FALLBACK = {  # job result -> (level to log, recorded levels that already report it, what happened)
    "failure": ("error", {"error"}, "failed without reporting it, see the job log"),
    "cancelled": ("warning", {"warning", "error"}, "was cancelled without reporting it"),
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
    recorded: dict[str, str] = {}  # job -> level its state file reports
    for path in paths:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            log(str(state["pipeline"]), state["level"], str(state["message"]))
            recorded[path.stem] = state["level"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            failed = True
            log(path.name, "error", f"unreadable pipeline state: {type(error).__name__}: {error}")
    for job, need in json.loads(needs_json).items():
        if need["result"] in FALLBACK:
            level, covered_by, what = FALLBACK[need["result"]]
            if recorded.get(job) not in covered_by:
                log(job, level, f"{job} {what}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state"), os.environ.get("NEEDS", "{}")))
