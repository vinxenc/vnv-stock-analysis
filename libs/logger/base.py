from abc import ABC, abstractmethod


class Logger(ABC):
    """What the code needs from a logger; an adapter maps it onto a concrete logging library."""

    @abstractmethod
    def debug(self, msg: str, *args: object) -> None:
        """Log `msg % args` at DEBUG."""

    @abstractmethod
    def info(self, msg: str, *args: object) -> None:
        """Log `msg % args` at INFO."""

    @abstractmethod
    def warning(self, msg: str, *args: object) -> None:
        """Log `msg % args` at WARNING."""

    @abstractmethod
    def error(self, msg: str, *args: object) -> None:
        """Log `msg % args` at ERROR."""
