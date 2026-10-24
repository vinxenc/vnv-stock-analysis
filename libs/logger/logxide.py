from logxide import logging

from .base import Logger


class LogxideLogger(Logger):
    """Adapter over logxide's stdlib-style API. Output goes to stderr."""

    def __init__(self, name: str, level: int = logging.INFO, fmt: str = "%(levelname)s %(message)s") -> None:
        logging.basicConfig(level=level, format=fmt)  # process-wide (also quiets third-party libs); first call wins
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)  # per logger, so it holds even if the root logger was configured elsewhere

    def debug(self, msg: str, *args: object) -> None:
        self._logger.debug(msg, *args)

    def info(self, msg: str, *args: object) -> None:
        self._logger.info(msg, *args)

    def warning(self, msg: str, *args: object) -> None:
        self._logger.warning(msg, *args)

    def error(self, msg: str, *args: object) -> None:
        self._logger.error(msg, *args)
