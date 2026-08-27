# tests/rclone/test_binary.py
import io, zipfile, hashlib, subprocess
import pytest
from src.rclone.binary import RcloneBinary
from src.core import paths, constants

def _fake_zip(inner_name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"rclone-v1.69.1-linux-amd64/{inner_name}", content)
    return buf.getvalue()

def test_uses_system_rclone_when_version_ok(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/rclone")
    monkeypatch.setattr(
        RcloneBinary, "_probe_version",
        lambda self, path: (1, 69, 0)
    )
    b = RcloneBinary()
    assert b.resolve() == "/usr/bin/rclone"

def test_rejects_old_system_rclone_then_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/rclone")
    monkeypatch.setattr(RcloneBinary, "_probe_version", lambda self, path: (1, 50, 0))
    payload = b"#!/bin/sh\necho rclone\n"
    zbytes = _fake_zip("rclone", payload)
    sha = hashlib.sha256(zbytes).hexdigest()
    monkeypatch.setattr(constants, "rclone_download_info", lambda: ("http://x/rclone.zip", sha))
    monkeypatch.setattr(RcloneBinary, "_http_get", lambda self, url: zbytes)
    b = RcloneBinary()
    resolved = b.resolve()
    assert resolved == str(paths.get_rclone_binary_path())
    assert paths.get_rclone_binary_path().exists()

def test_download_rejects_bad_checksum(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "get_app_dir", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda n: None)
    monkeypatch.setattr(constants, "rclone_download_info", lambda: ("http://x/rclone.zip", "0"*64))
    monkeypatch.setattr(RcloneBinary, "_http_get", lambda self, url: _fake_zip("rclone", b"x"))
    with pytest.raises(RuntimeError, match="checksum"):
        RcloneBinary().resolve()
