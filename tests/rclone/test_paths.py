# tests/rclone/test_paths.py
from src.core import paths, constants


def test_rclone_paths_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    assert paths.get_rclone_dir() == tmp_path / ".dm-sync" / "rclone"
    assert paths.get_rclone_config_path() == paths.get_rclone_dir() / "rclone.conf"
    assert paths.get_rclone_binary_path().parent == paths.get_rclone_dir()
    assert paths.get_rclone_pid_path() == paths.get_rclone_dir() / "rcd.pid"
    assert paths.get_rclone_dir().is_dir()  # created on access


def test_rclone_constants_present():
    assert constants.RCLONE_PINNED_VERSION
    assert constants.RCLONE_REMOTE_NAME == "synchotic"
    plat = constants.rclone_download_info()  # (url, sha256) for current platform
    assert plat[0].startswith("https://downloads.rclone.org/")
    assert len(plat[1]) == 64
