"""Rescan has to tell the truth about whether it can do anything.

Scanning needs OAuth. Without it _start_background_scan returns before doing any
work, so an enabled Rescan row silently does nothing and reads as a broken
button. It also used to throw the cursor back to the top of the list, which made
a working Rescan look like a no-op too.
"""
import pytest

from src.config.settings import UserSettings
from src.ui.screens.home import show_main_menu


class _Auth:
    def __init__(self, signed_in):
        self.is_signed_in = signed_in
        self.session_expired = False


@pytest.fixture
def build(monkeypatch, tmp_path):
    """Build the home menu and hand back its items, without drawing anything."""
    def run(auth=None, selected=0, press=None):
        captured = {}

        def fake_run(self, initial_index=0):
            captured["items"] = self.items
            captured["initial_index"] = initial_index
            if press is None:
                return None  # Esc
            # Stand in for the user landing on `press` and hitting Enter.
            idx = next(i for i, it in enumerate(self.items)
                       if getattr(it, "label", "") and press in it.label)
            self._selected = idx
            from chotic_ui.widgets.menu import MenuResult
            return MenuResult(self.items[idx], "enter")

        monkeypatch.setattr("chotic_ui.widgets.menu.Menu.run", fake_run, raising=False)
        monkeypatch.setattr("src.ui.widgets.menu.Menu.run", fake_run, raising=False)
        captured["returned"] = show_main_menu(
            folders=[],
            user_settings=UserSettings(tmp_path / "settings.json"),
            selected_index=selected,
            auth=auth,
        )
        return captured
    return run


def _rescan(items):
    return next(i for i in items
                if getattr(i, "label", "") and "Rescan" in i.label)


class TestSignedOut:
    def test_it_is_greyed_out_and_says_why(self, build):
        row = _rescan(build(auth=None)["items"])
        assert row.disabled is True
        assert row.description == "Logged out"

    def test_it_cannot_be_activated(self, build):
        """disabled is only visual. locked is what actually blocks Enter, and
        without it the row would still fire an action that does nothing."""
        assert _rescan(build(auth=None)["items"]).locked is True

    def test_a_signed_out_auth_object_counts_as_logged_out(self, build):
        row = _rescan(build(auth=_Auth(False))["items"])
        assert row.disabled is True
        assert row.description == "Logged out"


class TestSignedIn:
    def test_it_is_available(self, build):
        row = _rescan(build(auth=_Auth(True))["items"])
        assert row.disabled is False
        assert row.locked is False
        assert row.description != "Logged out"
