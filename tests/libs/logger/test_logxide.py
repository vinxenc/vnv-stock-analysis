import logxide
import pytest

from libs.logger import Logger, LogxideLogger


def test_interface_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        Logger()  # type: ignore[abstract]


def test_levels_reach_stderr_and_debug_is_filtered(capfd: pytest.CaptureFixture[str]) -> None:
    log = LogxideLogger("test_logxide")
    log.debug("d %s", 1)
    log.info("i %s", 2)
    log.warning("w %s", 3)
    log.error("e %s", 4)
    logxide.flush()

    err = capfd.readouterr().err
    assert "INFO i 2" in err
    assert "WARNING w 3" in err
    assert "ERROR e 4" in err
    assert "d 1" not in err
