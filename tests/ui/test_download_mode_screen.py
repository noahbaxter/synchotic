# tests/ui/test_download_mode_screen.py
"""The first-run chooser.

rclone must lead: verification was rejected, so it is the only path that gets a
new user the full library. anonymous must be labelled as the degraded fallback it
is, since it skips roughly half of every drive.
"""
from src.config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                 DOWNLOAD_MODE_RCLONE)
from src.ui.screens.download_mode import choose_download_mode


class _Result:
    def __init__(self, item):
        self.item = item

    @property
    def value(self):
        return self.item.value


def _captured(monkeypatch, pick=0):
    """Run the screen without a terminal, returning (menu, selected_value)."""
    seen = {}

    def fake_run(self, initial_index=0):
        seen["menu"] = self
        seen["initial"] = initial_index
        return _Result(self.items[pick]) if pick is not None else None

    monkeypatch.setattr("src.ui.widgets.menu.Menu.run", fake_run, raising=False)
    monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", fake_run, raising=False)
    return seen


def test_rclone_is_first_and_default_selection(monkeypatch):
    seen = _captured(monkeypatch, pick=0)
    assert choose_download_mode() == DOWNLOAD_MODE_RCLONE
    assert seen["menu"].items[0].value == DOWNLOAD_MODE_RCLONE
    assert seen["initial"] == 0


def test_all_three_modes_offered_in_priority_order(monkeypatch):
    seen = _captured(monkeypatch, pick=0)
    choose_download_mode()
    assert [i.value for i in seen["menu"].items] == [
        DOWNLOAD_MODE_RCLONE, DOWNLOAD_MODE_BYOC, DOWNLOAD_MODE_ANONYMOUS,
    ]


def test_embedded_oauth_is_not_offered(monkeypatch):
    """The 100-user cap is full, so offering it would just fail for new users."""
    seen = _captured(monkeypatch, pick=0)
    choose_download_mode()
    assert "oauth" not in [i.value for i in seen["menu"].items]


def test_anonymous_warns_that_charts_will_be_missing(monkeypatch):
    seen = _captured(monkeypatch, pick=2)
    assert choose_download_mode() == DOWNLOAD_MODE_ANONYMOUS
    anon = seen["menu"].items[2]
    blurb = f"{anon.label} {anon.description}".lower()
    assert "not download" in blurb or "missing" in blurb
    assert "limited" in blurb


def test_current_choice_is_preselected(monkeypatch):
    seen = _captured(monkeypatch, pick=1)
    choose_download_mode(current=DOWNLOAD_MODE_BYOC)
    assert seen["initial"] == 1


def test_escape_returns_none(monkeypatch):
    _captured(monkeypatch, pick=None)
    assert choose_download_mode() is None
