"""Log every pipeline state file as a coloured GitHub Actions annotation.

Usage: [NEEDS='<toJSON(needs)>'] python3 scripts/notification.py [state_directory]      (default: state)
Reads `*.json` files of {"level": "info"|"warning"|"error", "message": ..., "pipeline": ...} (written by
scripts/pipeline_state.py): info -> ::notice, warning -> ::warning, error -> ::error, titled with the pipeline name.
$NEEDS (the workflow's `toJSON(needs)`) is the fallback for a job that died before it could write its file (failed
checkout, runner lost): a failed job without a state file is logged as an error, a cancelled one as a warning.
A file that cannot be read or has an unknown level is logged as an error and makes the exit code 1.
Standard library only.
"""
import json
import os
import sys
from pathlib import Path

COMMANDS = {"info": "notice", "warning": "warning", "error": "error"}
NO_STATE = {  # job result -> (level, what happened)
    "failure": ("error", "failed before it could write its state, see the job log"),
    "cancelled": ("warning", "was cancelled before it could write its state"),
}


def escape(text: str, *, prop: bool = False) -> str:
    """Escape for a workflow command: message data needs % and newlines, a property also `:` and `,`."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def annotation(command: str, title: str, message: str) -> str:
    return f"::{command} title={escape(title, prop=True)}::{escape(message)}"


def main(directory: Path = Path("state"), needs_json: str = "{}") -> int:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        print(annotation("warning", "notification", f"no pipeline state found in {directory}"))
    failed = False
    for path in paths:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            print(annotation(COMMANDS[state["level"]], str(state["pipeline"]), str(state["message"])))
        except (OSError, ValueError, KeyError, TypeError) as error:
            failed = True
            print(annotation("error", path.name, f"unreadable pipeline state: {type(error).__name__}: {error}"))
    for job, need in json.loads(needs_json).items():
        if job not in {path.stem for path in paths} and need["result"] in NO_STATE:
            level, what = NO_STATE[need["result"]]
            print(annotation(COMMANDS[level], job, f"{job} {what}"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state"), os.environ.get("NEEDS", "{}")))
