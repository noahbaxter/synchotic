"""Shared setup for the manual test harnesses.

`bootstrap` is what lets one script drive two different checkouts: it puts the
chosen repo at the front of sys.path, so `import src.*` resolves to that tree's
code. That is how parity_check compares dev against a feature branch.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


def bootstrap(repo: Path, root: Path | None = None) -> Path:
    """Point the app at `repo`'s code and an isolated data root.

    Must run before any `src.*` import. Returns the data root.
    """
    root = Path(root) if root else Path(tempfile.mkdtemp(prefix="synchotic-test-"))
    root.mkdir(parents=True, exist_ok=True)
    os.environ["SYNCHOTIC_ROOT"] = str(root)

    repo = Path(repo).resolve()
    sys.path.insert(0, str(repo))
    # chotic-ui is a submodule installed editable in a real venv; add it directly
    # so these scripts work without one. Absent on branches predating the swap.
    vendored = repo / "vendor" / "chotic-ui"
    if vendored.exists():
        sys.path.insert(0, str(vendored))
    return root


def stub_rclone() -> None:
    """Disable the tier-4 second pass.

    Without this, any unattended sync that hits a blocked file downloads the
    rclone binary and then blocks forever inside `rclone config create` waiting
    for a browser consent nobody is there to click. folder_sync does
    `from .. import rclone` at call time, so patching the module object works.

    Also keeps parity comparisons honest: dev has no tier 4, so the branch must
    be measured with tier 4 off or the two trees are not comparable.
    """
    import src.rclone as rclone_mod

    class _Blocked:
        def ensure_authed(self):
            return False

        def __enter__(self):
            raise RuntimeError("rclone disabled by harness")

        def __exit__(self, *exc):
            return False

    rclone_mod.is_authed = lambda: False
    rclone_mod.RcloneSession = _Blocked


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_fixture(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def fixture_folder(spec: dict) -> dict:
    """Fixture -> the folder dict FolderSync.sync_folder expects."""
    files = [{k: v for k, v in e.items() if k != "expect"} for e in spec["files"]]
    return {"name": spec["name"], "folder_id": spec["folder_id"], "files": files}


def snapshot_tree(base: Path) -> dict:
    """relpath -> {size, md5} for every chart file under base.

    Skips the library state dir. Markers and ownership records live inside the
    library now, and they are our bookkeeping, not the user's charts. Including
    them makes every comparison fail on incidental differences.
    """
    out = {}
    if not base.exists():
        return out
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(base).as_posix()
        if rel == ".dm-sync" or rel.startswith(".dm-sync/"):
            continue
        out[rel] = {"size": path.stat().st_size, "md5": file_md5(path)}
    return out


def snapshot_markers(data_dir: Path) -> dict:
    """Marker filename -> md5 of contents. Markers are the purge source of truth."""
    markers = data_dir / "markers"
    out = {}
    if not markers.exists():
        return out
    for path in sorted(markers.rglob("*")):
        if path.is_file():
            out[path.relative_to(markers).as_posix()] = file_md5(path)
    return out


def diff_snapshots(a: dict, b: dict, label_a: str, label_b: str) -> list[str]:
    """Human-readable differences between two snapshot_tree results."""
    problems = []
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    for rel in only_a:
        problems.append(f"missing from {label_b}: {rel} ({a[rel]['size']} B)")
    for rel in only_b:
        problems.append(f"extra in {label_b}: {rel} ({b[rel]['size']} B)")
    for rel in sorted(set(a) & set(b)):
        if a[rel]["md5"] != b[rel]["md5"]:
            problems.append(
                f"content differs: {rel} "
                f"({label_a}={a[rel]['size']} B, {label_b}={b[rel]['size']} B)"
            )
    return problems
