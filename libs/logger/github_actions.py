import sys
from typing import TextIO

from .base import Logger


def escape(text: str, *, prop: bool = False) -> str:
    """Escape for a workflow command: message data needs % and newlines, a property also `:` and `,`."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


class GithubActionsLogger(Logger):
    """Adapter over GitHub Actions workflow commands: the runner turns a stdout line like
    `::warning title=<title>::<message>` into a coloured annotation (info -> notice, debug -> hidden debug line).

    The commands must be on stdout (not stderr) and start the line, so unlike `LogxideLogger` there is no prefix.
    """

    def __init__(self, title: str, stream: TextIO | None = None) -> None:
        self._title = title
        self._stream = stream  # None: sys.stdout at call time, so redirecting it (tests, capture) works

    def _emit(self, command: str, msg: str, args: tuple[object, ...]) -> None:
        message = escape(msg % args if args else msg)
        title = "" if command == "debug" else f" title={escape(self._title, prop=True)}"
        (self._stream or sys.stdout).write(f"::{command}{title}::{message}\n")

    def debug(self, msg: str, *args: object) -> None:
        self._emit("debug", msg, args)

    def info(self, msg: str, *args: object) -> None:
        self._emit("notice", msg, args)

    def warning(self, msg: str, *args: object) -> None:
        self._emit("warning", msg, args)

    def error(self, msg: str, *args: object) -> None:
        self._emit("error", msg, args)
