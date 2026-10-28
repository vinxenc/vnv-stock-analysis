"""Log every pipeline state file as a coloured GitHub Actions annotation.

Usage: python3 scripts/notification.py [state_directory]      (default: state)
Reads `*.json` files of {"level": "info"|"warning"|"error", "message": ..., "pipeline": ...} (written by
scripts/pipeline_state.py): info -> ::notice, warning -> ::warning, error -> ::error, titled with the pipeline name.
A file that cannot be read or has an unknown level is logged as an error and makes the exit code 1.
Standard library only.
"""
import json
import sys
from pathlib import Path

COMMANDS = {"info": "notice", "warning": "warning", "error": "error"}


def escape(text: str, *, prop: bool = False) -> str:
    """Escape for a workflow command: message data needs % and newlines, a property also `:` and `,`."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def annotation(command: str, title: str, message: str) -> str:
    return f"::{command} title={escape(title, prop=True)}::{escape(message)}"


def main(directory: Path = Path("state")) -> int:
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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*map(Path, sys.argv[1:2])))
