"""What the first-run chooser actually paints.

The rest of the chooser tests stub out Menu.run, so they assert on MenuItem data
that may never reach the screen. This one renders for real: the box has to close
at narrow widths, and the text explaining each mode has to be visible, because
that text is the whole reason the screen exists.
"""
import io
import re
import sys

import pytest

from src.config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                 DOWNLOAD_MODE_RCLONE)
from src.ui.screens.download_mode import choose_download_mode

ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _paint(monkeypatch, columns=80, lines=40, current=""):
    """Render the chooser once at a fixed terminal size, return visible lines.

    Menu._render writes to sys.__stdout__, so we hand it a StringIO rather than
    capturing a file descriptor. Capturing the fd would inherit the platform's
    console encoding, and box-drawing characters are not representable in the
    Windows default (cp1252), which fails on the encode rather than the assert.
    """
    monkeypatch.setenv("COLUMNS", str(columns))
    monkeypatch.setenv("LINES", str(lines))

    screen = io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", screen)

    def render_once(self, initial_index=0):
        self._selected = initial_index
        self._render()
        return None

    monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", render_once, raising=False)
    monkeypatch.setattr("src.ui.widgets.menu.Menu.run", render_once, raising=False)

    choose_download_mode(current=current)
    return [ANSI.sub("", ln) for ln in screen.getvalue().split("\n")]


def _box_lines(painted):
    return [ln for ln in painted if ln.startswith(("│", "╭", "╰", "├"))]


@pytest.mark.parametrize("columns", [80, 100, 120])
def test_box_closes_at_every_width(monkeypatch, columns):
    """A line wider than the box means the border broke and text spilled out."""
    painted = _paint(monkeypatch, columns=columns)
    box = _box_lines(painted)
    assert box, "nothing was painted"
    widths = {len(ln) for ln in box}
    assert len(widths) == 1, (
        f"box lines have mismatched widths at {columns} cols: {sorted(widths)}\n"
        + "\n".join(box)
    )


@pytest.mark.parametrize("mode,phrase", [
    (DOWNLOAD_MODE_RCLONE, "One Google consent click"),
    (DOWNLOAD_MODE_BYOC, "Google Cloud project"),
    (DOWNLOAD_MODE_ANONYMOUS, "Skips every blocked archive"),
])
def test_selected_mode_explains_itself(monkeypatch, mode, phrase):
    """The consequence of a choice must reach the screen, not just MenuItem data."""
    painted = "\n".join(_paint(monkeypatch, current=mode))
    assert phrase in painted, f"description missing from render: {phrase!r}"


def test_detail_pane_height_does_not_shift_between_selections(monkeypatch):
    """A box that resizes as you arrow through makes the whole screen jump."""
    heights = {len(_box_lines(_paint(monkeypatch, current=m)))
               for m in (DOWNLOAD_MODE_RCLONE, DOWNLOAD_MODE_BYOC, DOWNLOAD_MODE_ANONYMOUS)}
    assert len(heights) == 1, f"box height changes with selection: {sorted(heights)}"
