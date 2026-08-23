"""Changing download mode after first run.

The chooser used to run once, on first launch, and nothing could reach it again.
Someone who picked anonymous to get going, or whose rclone consent lapsed, was
stuck with that decision.
"""
import pytest

from src.config.settings import (DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC,
                                 DOWNLOAD_MODE_RCLONE)
from src.ui.screens.download_mode import change_download_mode, connection_step_for


class FakeSettings:
    def __init__(self, mode=""):
        self.download_mode = mode
        self.saves = 0

    def save(self):
        self.saves += 1


class FakeSync:
    def __init__(self, mode=""):
        self.download_mode = mode


def _pick(monkeypatch, value):
    seen = {}

    def fake_chooser(current=""):
        seen["current"] = current
        return value

    monkeypatch.setattr("src.ui.screens.download_mode.choose_download_mode", fake_chooser)
    return seen


class TestChanging:
    def test_new_mode_is_persisted(self, monkeypatch):
        _pick(monkeypatch, DOWNLOAD_MODE_BYOC)
        settings = FakeSettings(DOWNLOAD_MODE_ANONYMOUS)
        assert change_download_mode(settings) == DOWNLOAD_MODE_BYOC
        assert settings.download_mode == DOWNLOAD_MODE_BYOC
        assert settings.saves == 1

    def test_live_sync_picks_it_up_without_restart(self, monkeypatch):
        """Otherwise the change only takes effect next launch."""
        _pick(monkeypatch, DOWNLOAD_MODE_RCLONE)
        sync = FakeSync(DOWNLOAD_MODE_ANONYMOUS)
        change_download_mode(FakeSettings(DOWNLOAD_MODE_ANONYMOUS), sync)
        assert sync.download_mode == DOWNLOAD_MODE_RCLONE

    def test_current_mode_is_shown_as_selected(self, monkeypatch):
        seen = _pick(monkeypatch, DOWNLOAD_MODE_RCLONE)
        change_download_mode(FakeSettings(DOWNLOAD_MODE_BYOC))
        assert seen["current"] == DOWNLOAD_MODE_BYOC

    def test_backing_out_changes_nothing(self, monkeypatch):
        _pick(monkeypatch, None)
        settings = FakeSettings(DOWNLOAD_MODE_ANONYMOUS)
        sync = FakeSync(DOWNLOAD_MODE_ANONYMOUS)
        assert change_download_mode(settings, sync) is None
        assert settings.download_mode == DOWNLOAD_MODE_ANONYMOUS
        assert settings.saves == 0
        assert sync.download_mode == DOWNLOAD_MODE_ANONYMOUS


class TestConnectionStep:
    def test_rclone_connects_when_not_authed(self):
        assert connection_step_for(
            DOWNLOAD_MODE_RCLONE, rclone_authed=False, signed_in=False) == "rclone"

    def test_rclone_already_authed_needs_nothing(self):
        assert connection_step_for(
            DOWNLOAD_MODE_RCLONE, rclone_authed=True, signed_in=False) == ""

    def test_byoc_signs_in(self):
        assert connection_step_for(
            DOWNLOAD_MODE_BYOC, rclone_authed=False, signed_in=False) == "signin"

    def test_byoc_already_signed_in_needs_nothing(self):
        assert connection_step_for(
            DOWNLOAD_MODE_BYOC, rclone_authed=False, signed_in=True) == ""

    @pytest.mark.parametrize("authed,signed_in", [(False, False), (True, True)])
    def test_anonymous_never_opens_a_browser(self, authed, signed_in):
        """Anonymous is the choice for people who cannot complete consent."""
        assert connection_step_for(
            DOWNLOAD_MODE_ANONYMOUS, rclone_authed=authed, signed_in=signed_in) == ""
