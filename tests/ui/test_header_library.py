"""The library path, beside the version on every screen."""
import io
import re
from contextlib import redirect_stdout

from src.ui.components import header as header_module

# Colour and the erase-to-end-of-line the banner puts on every row. strip_ansi
# only knows the colours.
CSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _printed(monkeypatch, library, draw=None):
    monkeypatch.setattr("src.core.paths.get_library_path", lambda: library)
    # These tests are about drawing a library that exists. The unset case has
    # its own wording and its own test below.
    monkeypatch.setattr("src.core.paths.library_is_set", lambda: True)
    header_module.install_header()
    out = io.StringIO()
    with redirect_stdout(out):
        (draw or header_module.print_header)()
    return CSI.sub("", out.getvalue())


def test_every_screen_shows_it_not_only_the_sync_screen(monkeypatch, tmp_path):
    """The home screen and every menu draw the banner through chotic-ui, not
    through Synchotic's own header. Those are the screens that never had it."""
    from chotic_ui.components.header import print_header as chotic_print_header

    library = tmp_path / "Clone Hero" / "Songs"
    printed = _printed(monkeypatch, library, draw=chotic_print_header)

    assert "library → " in printed
    assert "Songs" in printed


def test_the_library_is_shown_beside_the_version(monkeypatch, tmp_path):
    library = tmp_path / "Clone Hero" / "Songs"
    printed = _printed(monkeypatch, library)

    version_line = [ln for ln in printed.split("\n") if " v" in ln][0]
    assert "Songs" in version_line


def test_a_path_under_home_is_shortened(monkeypatch):
    from pathlib import Path

    printed = _printed(monkeypatch, Path.home() / "Synchotic" / "Sync Charts")

    assert "~/Synchotic/Sync Charts" in printed
    assert str(Path.home()) not in printed


def test_moving_the_library_updates_the_header(monkeypatch, tmp_path):
    """The art is cached; the path must not be, or Settings changes nothing."""
    _printed(monkeypatch, tmp_path / "first")
    printed = _printed(monkeypatch, tmp_path / "second")

    assert "second" in printed
    assert "first" not in printed


def test_a_long_path_is_shortened_from_the_front(monkeypatch, tmp_path):
    """The end of a path is the part worth keeping.

    Cutting the tail leaves "/private/var/folders/9y/08s13t6j..." and loses the
    folder name, which is the only part anyone reads.
    """
    # chotic-ui draws the banner and reads the width from its own module; the
    # re-export under src.ui.primitives is a copy of the name, not the lookup.
    monkeypatch.setattr("chotic_ui.primitives.terminal.get_terminal_width",
                        lambda: 60)
    library = tmp_path.joinpath(*[f"deeply-nested-{i}" for i in range(8)], "Songs")
    printed = _printed(monkeypatch, library)

    status = [ln for ln in printed.split("\n") if " v" in ln][0]
    assert status.endswith("Songs")
    assert "…/" in status
    assert len(status) <= 60


def test_an_unset_library_says_so_on_every_screen(monkeypatch):
    """Nothing syncs until a library is chosen, so the banner says it instead
    of leaving the line blank and the reason buried in a settings pane."""
    monkeypatch.setattr("src.core.paths.library_is_set", lambda: False)
    header_module.install_header()
    out = io.StringIO()
    with redirect_stdout(out):
        header_module.print_header()

    assert "library → NOT SET" in CSI.sub("", out.getvalue())
