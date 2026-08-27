# tests/sync/test_download_mode.py
"""download_mode gates the rclone tier.

The bug this guards: with no way to decline, any sync hitting a blocked file
opened a consent browser. On a machine with no browser that stalled for the full
subprocess timeout before failing.
"""
import subprocess

import pytest

from src.config.settings import DOWNLOAD_MODES, UserSettings
from src.sync.download_planner import DownloadTask
from src.sync.folder_sync import FolderSync


def _blocked_task(tmp_path):
    return DownloadTask(file_id="ID", local_path=tmp_path / "Set" / "_download_a.7z",
                        size=1, md5="", is_archive=True, rel_path="Drive/Set/a.7z")


def _folder():
    return {"name": "Drive", "folder_id": "fid",
            "files": [{"id": "ID", "path": "Set/a.7z", "size": 1, "md5": ""}]}


@pytest.fixture
def one_blocked(monkeypatch, tmp_path):
    blocked = _blocked_task(tmp_path)
    monkeypatch.setattr("src.sync.downloader.FileDownloader.download_many",
                        lambda self, tasks, **kw: (0, 0, 1, [], False, 0, [blocked]))
    return blocked


@pytest.mark.parametrize("mode", ["anonymous", "byoc"])
def test_non_rclone_modes_never_touch_rclone(monkeypatch, tmp_path, one_blocked, mode):
    """No consent browser, no session, for a user who did not pick rclone."""
    def boom(*a, **kw):
        raise AssertionError(f"rclone consulted in {mode} mode")
    monkeypatch.setattr("src.rclone.is_authed", boom)
    monkeypatch.setattr("src.rclone.RcloneSession", boom)

    fs = FolderSync(client=None, auth_token=None, download_mode=mode)
    downloaded, _, errors, _, _, _ = fs.sync_folder(_folder(), tmp_path)

    assert downloaded == 0
    assert errors == 1  # still reported as failed, not silently dropped


def test_rclone_mode_still_uses_the_tier(monkeypatch, tmp_path, one_blocked):
    seen = {}

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def ensure_authed(self, timeout=120.0): return True
        downloader = type("D", (), {
            "download": lambda self, tasks, cancel_check=None, progress_cb=None: (
                seen.update(ids=[t.file_id for t in tasks]) or (["ID"], [])
            )
        })()

    monkeypatch.setattr("src.rclone.is_authed", lambda: True)
    monkeypatch.setattr("src.rclone.RcloneSession", FakeSession)
    monkeypatch.setattr("src.sync.downloader.FileDownloader.process_archive",
                        lambda self, task, rel=None: (True, "", {}))

    fs = FolderSync(client=None, auth_token=None, download_mode="rclone")
    fs.sync_folder(_folder(), tmp_path)
    assert seen["ids"] == ["ID"]


def test_default_mode_is_rclone(tmp_path):
    """Unset settings must not silently disable the tier that unblocks users."""
    fs = FolderSync(client=None, auth_token=None)
    assert fs.download_mode == "rclone"


class TestSettingsPersistence:
    def test_roundtrip(self, tmp_path):
        s = UserSettings.load(tmp_path / "settings.json")
        assert s.download_mode == ""  # unset means "ask"
        s.download_mode = "anonymous"
        s.save()
        assert UserSettings.load(tmp_path / "settings.json").download_mode == "anonymous"

    def test_unknown_value_falls_back_to_unset(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text('{"download_mode": "carrier-pigeon"}')
        assert UserSettings.load(path).download_mode == ""

    def test_every_mode_survives_roundtrip(self, tmp_path):
        for mode in DOWNLOAD_MODES:
            path = tmp_path / f"{mode}.json"
            s = UserSettings.load(path)
            s.download_mode = mode
            s.save()
            assert UserSettings.load(path).download_mode == mode


def test_consent_timeout_returns_false_instead_of_raising(monkeypatch):
    """A browserless box must fail fast, not propagate TimeoutExpired."""
    from src.rclone.config import RcloneConfig

    def timeout_runner(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kw.get("timeout", 0))

    cfg = RcloneConfig("rclone", runner=timeout_runner)
    assert cfg.create_remote(timeout=0.01) is False
