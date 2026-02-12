"""Pytest configuration and shared fixtures."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.sync.markers import save_marker
from src.sync.cache import SyncCache


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "stress: stress tests with large data (skipped in CI)"
    )


@dataclass
class SyncEnv:
    """Isolated sync environment for integration tests."""
    tmp: Path
    base_path: Path
    markers_dir: Path

    def make_folder(self, folder_name: str, setlist: str = "") -> Path:
        """Create a folder (drive/setlist) directory on disk."""
        if setlist:
            p = self.base_path / folder_name / setlist
        else:
            p = self.base_path / folder_name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def make_files(self, folder_name: str, file_specs: dict[str, int]) -> None:
        """Create files on disk with specified sizes.

        Args:
            folder_name: Drive folder name
            file_specs: {relative_path: size_bytes} — paths relative to folder
        """
        folder_path = self.base_path / folder_name
        for rel_path, size in file_specs.items():
            full = folder_path / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(b"\x00" * size)

    def make_marker(
        self,
        archive_path: str,
        md5: str,
        extracted_files: dict[str, int],
    ) -> Path:
        """Create a marker file. archive_path like 'DriveName/Setlist/pack.7z'."""
        return save_marker(
            archive_path=archive_path,
            md5=md5,
            extracted_files=extracted_files,
        )

    def make_manifest_entry(
        self,
        path: str,
        file_id: str = "",
        size: int = 1000,
        md5: str = "abc123",
        modified: str = "2025-01-01T00:00:00",
    ) -> dict:
        """Build a single manifest file entry."""
        return {
            "id": file_id or f"id_{path.replace('/', '_')}",
            "path": path,
            "size": size,
            "md5": md5,
            "modified": modified,
        }

    def make_folder_dict(
        self,
        name: str,
        folder_id: str = "",
        files: list[dict] | None = None,
        is_custom: bool = False,
    ) -> dict:
        """Build a folder dict for API consumption."""
        return {
            "name": name,
            "folder_id": folder_id or f"fid_{name}",
            "files": files,
            "is_custom": is_custom,
        }


@pytest.fixture
def sync_env(monkeypatch):
    """Create an isolated sync environment with temp dirs and monkeypatched globals."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        base_path = tmp / "base_path"
        base_path.mkdir()
        markers_dir = tmp / ".dm-sync" / "markers"
        markers_dir.mkdir(parents=True)

        # Monkeypatch markers dir
        monkeypatch.setattr("src.sync.markers.get_markers_dir", lambda: markers_dir)

        # Fresh SyncCache per test (prevent cross-test leakage from global)
        fresh_cache = SyncCache()
        monkeypatch.setattr("src.sync.cache._cache", fresh_cache)

        yield SyncEnv(tmp=tmp, base_path=base_path, markers_dir=markers_dir)


# ---------------------------------------------------------------------------
# Reusable scenario builders (functions, not fixtures)
# ---------------------------------------------------------------------------

def make_synced_archive(
    env: SyncEnv,
    folder_name: str,
    setlist: str,
    archive_name: str,
    md5: str,
    chart_files: dict[str, int],
    archive_size: int = 1000,
) -> dict:
    """Create files on disk + marker + return manifest entry.

    chart_files: {rel_path_from_folder: size} e.g. {"Setlist/Chart/song.ini": 100}
    """
    env.make_files(folder_name, chart_files)
    archive_path = f"{folder_name}/{setlist}/{archive_name}"
    env.make_marker(archive_path, md5, chart_files)

    return env.make_manifest_entry(
        path=f"{setlist}/{archive_name}",
        size=archive_size,
        md5=md5,
    )


def make_unsynced_archive(
    env: SyncEnv,
    folder_name: str,
    setlist: str,
    archive_name: str,
    md5: str,
    archive_size: int = 1000,
) -> dict:
    """Return manifest entry only (no files, no marker)."""
    return env.make_manifest_entry(
        path=f"{setlist}/{archive_name}",
        size=archive_size,
        md5=md5,
    )


def make_synced_loose_file(
    env: SyncEnv,
    folder_name: str,
    rel_path: str,
    size: int,
) -> dict:
    """Create file on disk + return manifest entry."""
    env.make_files(folder_name, {rel_path: size})
    return env.make_manifest_entry(path=rel_path, size=size, md5="")


def make_unsynced_loose_file(
    rel_path: str,
    size: int,
    env: SyncEnv | None = None,
) -> dict:
    """Return manifest entry only (no file on disk)."""
    if env:
        return env.make_manifest_entry(path=rel_path, size=size, md5="")
    return {
        "id": f"id_{rel_path.replace('/', '_')}",
        "path": rel_path,
        "size": size,
        "md5": "",
        "modified": "2025-01-01T00:00:00",
    }


def make_corrupted_file(
    env: SyncEnv,
    folder_name: str,
    rel_path: str,
    manifest_size: int,
    actual_size: int | None = None,
) -> dict:
    """Create file with wrong size on disk + return manifest entry."""
    wrong_size = actual_size if actual_size is not None else manifest_size // 2
    env.make_files(folder_name, {rel_path: wrong_size})
    return env.make_manifest_entry(path=rel_path, size=manifest_size, md5="")
