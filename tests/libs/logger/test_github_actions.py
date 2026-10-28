import io
import subprocess
import sys
from pathlib import Path

import pytest

from libs.logger import GithubActionsLogger
from libs.logger.github_actions import escape


def test_each_level_is_a_workflow_command() -> None:
    stream = io.StringIO()
    log = GithubActionsLogger("my_job", stream)
    log.debug("d %s", 1)
    log.info("i %s", 2)
    log.warning("w %s", 3)
    log.error("e %s", 4)
    assert stream.getvalue().splitlines() == [
        "::debug::d 1",  # the debug command takes no title
        "::notice title=my_job::i 2",
        "::warning title=my_job::w 3",
        "::error title=my_job::e 4",
    ]


def test_default_stream_is_stdout_at_call_time(capsys: pytest.CaptureFixture[str]) -> None:
    GithubActionsLogger("job").info("hello")
    assert capsys.readouterr().out == "::notice title=job::hello\n"


def test_percent_without_args_is_literal_and_special_characters_are_escaped() -> None:
    stream = io.StringIO()
    GithubActionsLogger("a:b,c", stream).info("50% done\nnext")
    assert stream.getvalue() == "::notice title=a%3Ab%2Cc::50%25 done%0Anext\n"


def test_escape_only_escapes_properties_more() -> None:
    assert escape("a:b,c\r") == "a:b,c%0D"
    assert escape("a:b,c\r", prop=True) == "a%3Ab%2Cc%0D"


def test_package_and_notification_import_without_logxide() -> None:
    """The notification job runs on system Python after a failed `uv sync`: logxide may be missing."""
    code = "import sys; sys.modules['logxide'] = None; import scripts.notification; from libs.logger import Logger"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).parents[3])
    assert result.returncode == 0, result.stderr
