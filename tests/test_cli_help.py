"""--help has to print somewhere the user can still read afterwards.

The app draws in the alternate screen buffer, which is discarded on exit. So
anything argparse prints after that buffer opens is thrown away: --help and a
rejected argument both printed into it and the user saw an empty screen.

These run under a pty on purpose. enter_alt_screen checks isatty() first, so a
piped subprocess never emits the escape and would pass whatever the app does.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# pty, termios and fcntl are POSIX only, and importing them at module level
# aborts collection for the whole run on Windows. Windows cannot test this
# anyway: without a ConPTY the app never sees a terminal, enter_alt_screen
# returns early, and --help prints no matter which order main() uses.
pytestmark = pytest.mark.skipif(os.name != "posix",
                                reason="needs a pty; POSIX only")

ROOT = Path(__file__).resolve().parent.parent
ENTER_ALT_SCREEN = "\033[?1049h"
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")


def _run_on_a_tty(*args, timeout=120):
    """Run sync.py attached to a pty and return everything it wrote."""
    import pty
    import select

    primary, secondary = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "sync.py"), *args],
        cwd=ROOT, stdin=secondary, stdout=secondary, stderr=secondary,
        close_fds=True,
    )
    os.close(secondary)

    chunks = []
    while True:
        ready, _, _ = select.select([primary], [], [], timeout)
        if not ready:
            break
        try:
            data = os.read(primary, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)

    os.close(primary)
    proc.wait(timeout=timeout)
    return proc.returncode, b"".join(chunks).decode("utf-8", "replace")


@pytest.fixture(scope="module")
def helped():
    return _run_on_a_tty("--help")


def test_the_pty_harness_really_gives_the_app_a_terminal(helped):
    """Without this the other two pass no matter what the app does."""
    _, output = helped
    assert "\x1b" in output, "no escape sequences at all, so isatty() was False"


def test_help_prints_the_usage(helped):
    code, output = helped

    assert "--download-mode" in ANSI.sub("", output)
    assert code == 0


def test_help_never_opens_the_alternate_screen(helped):
    """The buffer is discarded on exit, so text written into it is lost."""
    _, output = helped

    assert ENTER_ALT_SCREEN not in output


def test_a_rejected_argument_is_readable_too():
    code, output = _run_on_a_tty("--download-mode", "nonsense")

    assert code != 0
    assert "invalid choice" in ANSI.sub("", output)
    assert ENTER_ALT_SCREEN not in output
