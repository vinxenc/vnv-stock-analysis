from typing import TYPE_CHECKING

from .base import Logger
from .github_actions import GithubActionsLogger

if TYPE_CHECKING:
    from .logxide import LogxideLogger

__all__ = ["GithubActionsLogger", "Logger", "LogxideLogger"]


def __getattr__(name: str) -> type[Logger]:
    """`LogxideLogger` needs the third-party logxide: import it on first use, so the rest of this package (the
    notification job runs `GithubActionsLogger` after a failed `uv sync`) works without the dependencies installed."""
    if name == "LogxideLogger":
        from .logxide import LogxideLogger

        return LogxideLogger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
