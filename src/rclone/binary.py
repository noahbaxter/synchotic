"""Locate a usable rclone binary, or download+verify the pinned build."""
import hashlib, io, os, re, shutil, stat, subprocess, zipfile
from pathlib import Path
from typing import Optional, Tuple

from ..core import constants
from ..core.paths import get_rclone_binary_path


class RcloneBinary:
    def __init__(self):
        self._resolved: Optional[str] = None

    def resolve(self) -> str:
        """Return a path to a usable rclone, downloading the pinned build if needed."""
        if self._resolved:
            return self._resolved
        system = shutil.which("rclone")
        if system and self._version_ok(self._probe_version(system)):
            self._resolved = system
            return system
        managed = get_rclone_binary_path()
        if managed.exists() and self._version_ok(self._probe_version(str(managed))):
            self._resolved = str(managed)
            return self._resolved
        self._download_pinned(managed)
        self._resolved = str(managed)
        return self._resolved

    @staticmethod
    def _version_ok(v: Optional[Tuple[int, int, int]]) -> bool:
        return v is not None and v >= constants.RCLONE_MIN_SYSTEM_VERSION

    def _probe_version(self, path: str) -> Optional[Tuple[int, int, int]]:
        try:
            out = subprocess.run([path, "version"], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"rclone v(\d+)\.(\d+)\.(\d+)", out)
            return tuple(int(g) for g in m.groups()) if m else None
        except Exception:
            return None

    def _http_get(self, url: str) -> bytes:
        import requests
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        return r.content

    def _download_pinned(self, dest: Path) -> None:
        url, expected_sha = constants.rclone_download_info()
        data = self._http_get(url)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_sha:
            raise RuntimeError(f"rclone checksum mismatch: {actual} != {expected_sha}")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            inner = next(n for n in z.namelist() if n.endswith(("/rclone", "/rclone.exe")))
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(inner) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        if os.name != "nt":
            dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
