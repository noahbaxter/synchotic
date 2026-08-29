"""
File system utilities for DM Chart Sync.
"""

from pathlib import Path
from typing import Set, List, Tuple


def file_exists_with_size(path: Path, expected_size: int) -> bool:
    """Check if file exists and matches expected size."""
    if not path.exists():
        return False
    try:
        return path.stat().st_size == expected_size
    except Exception:
        return False


def find_unexpected_files(folder_path: Path, expected_paths: Set[Path]) -> List[Path]:
    """
    Find local files not in the expected set.

    Args:
        folder_path: Folder to scan
        expected_paths: Set of expected file paths

    Returns:
        List of paths to unexpected files
    """
    if not folder_path.exists():
        return []

    local_files = [f for f in folder_path.rglob("*") if f.is_file()]
    return [f for f in local_files if f not in expected_paths]


def find_unexpected_files_with_sizes(folder_path: Path, expected_paths: Set[Path]) -> List[Tuple[Path, int]]:
    """
    Find local files not in the expected set, with their sizes.

    Args:
        folder_path: Folder to scan
        expected_paths: Set of expected file paths

    Returns:
        List of (path, size) tuples for unexpected files
    """
    extra_files = find_unexpected_files(folder_path, expected_paths)
    result = []
    for f in extra_files:
        try:
            result.append((f, f.stat().st_size))
        except Exception:
            result.append((f, 0))
    return result


def system_tool_env() -> dict:
    """Environment for an OS helper we shell out to.

    PyInstaller points LD_LIBRARY_PATH at its own _internal dir and every child
    inherits it, so the helper loads our bundled libraries instead of the
    system's. On Fedora that meant xdg-open reached flatpak, which could not
    load libcrypto ("version OPENSSL_3.4.0 not found") and gave up without
    saying so: the file manager simply never opened. PyInstaller keeps the
    pre-launch value in LD_LIBRARY_PATH_ORIG, so put it back. A no-op off
    Linux, where neither variable exists.
    """
    import os
    import sys

    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = orig
    return env


def system_tools_on_path():
    """A context manager that cleans os.environ itself, then puts it back.

    For a library that spawns an OS helper out of reach of any env argument:
    webbrowser resolves to xdg-open on Linux and google-auth calls it from
    inside run_local_server, so being clean while it runs is the only way to
    hand it the system's libraries. Prefer system_tool_env wherever the spawn
    is ours to make; this changes the environment of the whole process.
    """
    import contextlib
    import os

    @contextlib.contextmanager
    def swap():
        before = os.environ.get("LD_LIBRARY_PATH")
        clean = system_tool_env().get("LD_LIBRARY_PATH")
        if clean is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = clean
        try:
            yield
        finally:
            if before is None:
                os.environ.pop("LD_LIBRARY_PATH", None)
            else:
                os.environ["LD_LIBRARY_PATH"] = before

    return swap()


def open_folder(path) -> bool:
    """Show a folder in the OS file manager. Returns False if that isn't possible.

    Best effort by design: a headless box has nothing to open, and the caller
    always prints the path as well, so failing here is not an error.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    path = Path(path)
    if not path.is_dir():
        return False
    if sys.platform == "darwin":
        cmd = ["open", str(path)]
    elif sys.platform == "win32":
        cmd = ["explorer", str(path)]
    else:
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return False
        cmd = ["xdg-open", str(path)]
    try:
        # explorer.exe returns 1 even when it succeeds, so the exit code is not
        # a usable signal on any platform here.
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=system_tool_env())
        return True
    except Exception:
        return False
