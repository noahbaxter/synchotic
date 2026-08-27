"""Native folder picker.

Synchotic is a TUI, so there is no toolkit to open a dialog with. Every platform
already ships something that can: AppleScript on macOS, WinForms on Windows, and
kdialog/zenity/yad on Linux. Shell out to whichever is there.

None of it is guaranteed. A headless run, an SSH session, or a stripped-down
distro has no picker at all, so every caller must keep the typed-path prompt as
a way through.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .logging import debug_log

# A dialog is modal and waits on a person, so there is no sensible deadline.
# This only guards against a helper that starts and then never draws anything.
_TIMEOUT = 300


def _child_env() -> dict:
    """Environment for a dialog helper.

    PyInstaller points LD_LIBRARY_PATH at its own _internal dir, and a child
    process inherits it: kdialog then loads our bundled libstdc++ instead of the
    system one and dies on a missing GLIBCXX, zenity dies on libssl. PyInstaller
    keeps the pre-launch value in LD_LIBRARY_PATH_ORIG, so put it back. A no-op
    off Linux, where neither variable exists.
    """
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = orig
    return env


def _has_display() -> bool:
    """True when a Linux session can actually put a window on screen."""
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def _linux_helpers() -> list:
    """Available dialog helpers, the one matching this desktop first.

    kdialog under Plasma and zenity under GNOME each give the file dialog the
    rest of that desktop uses. Either works anywhere, so the match is a
    preference, not a requirement.
    """
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    order = ["kdialog", "zenity", "yad"]
    if "gnome" in desktop or "xfce" in desktop or "cinnamon" in desktop:
        order = ["zenity", "yad", "kdialog"]
    return [h for h in order if shutil.which(h)]


def picker_available() -> bool:
    """True when pick_folder has something to open. Cheap enough to call while
    drawing a screen; used to decide whether to offer Browse at all."""
    if sys.platform == "darwin":
        return bool(shutil.which("osascript"))
    if sys.platform == "win32":
        return bool(shutil.which("powershell") or shutil.which("powershell.exe"))
    return _has_display() and bool(_linux_helpers())


def _run(cmd: list) -> "str | None":
    """Run a dialog helper.

    Returns the chosen path, "" when the user cancelled, or None when the helper
    could not run at all. Cancel and failure have to stay distinguishable: the
    Linux chain falls through to the next helper on None, and treating a cancel
    as failure would pop a second dialog in the user's face.
    """
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=_TIMEOUT, env=_child_env(), **kwargs)
    except (OSError, subprocess.TimeoutExpired) as e:
        debug_log(f"folder picker failed: {e}")
        return None
    if result.returncode != 0:
        # Every helper here exits non-zero on cancel, and so does a helper that
        # died on startup. stderr tells them apart: cancel is silent.
        if result.stderr.strip():
            debug_log(f"folder picker {cmd[0]}: {result.stderr.strip()[:200]}")
            return None
        return ""
    return result.stdout.strip()


def _applescript(title: str, start: Path) -> "str | None":
    def quote(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')

    # `default location` needs a folder that exists; AppleScript raises
    # otherwise and the dialog never opens.
    location = start if start.is_dir() else Path.home()
    script = (
        f'POSIX path of (choose folder with prompt "{quote(title)}" '
        f'default location POSIX file "{quote(str(location))}")'
    )
    return _run(["osascript", "-e", script])


def _winforms(title: str, start: Path) -> "str | None":
    def quote(s):
        return s.replace("'", "''")

    # -STA because the common file dialogs require a single-threaded apartment;
    # PowerShell 5 defaults to it but pwsh 7 does not.
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "[System.Windows.Forms.Application]::EnableVisualStyles();"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        f"$d.Description = '{quote(title)}';"
        f"$d.SelectedPath = '{quote(str(start))}';"
        "$d.ShowNewFolderButton = $true;"
        "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
        " { [Console]::Out.Write($d.SelectedPath) } else { exit 1 }"
    )
    exe = shutil.which("powershell") or shutil.which("powershell.exe") or "powershell"
    return _run([exe, "-NoProfile", "-NonInteractive", "-STA", "-Command", script])


def _linux(title: str, start: Path, helper: str) -> "str | None":
    if helper == "kdialog":
        return _run([helper, "--title", title, "--getexistingdirectory", str(start)])
    if helper == "zenity":
        # The trailing separator is what tells GTK to open *inside* the folder
        # rather than selecting it in its parent.
        return _run([helper, "--file-selection", "--directory",
                     f"--title={title}", f"--filename={start}{os.sep}"])
    return _run([helper, "--file", "--directory",
                 f"--title={title}", f"--filename={start}{os.sep}"])


def pick_folder(title: str, start=None) -> "Path | None":
    """Open the platform's folder dialog. Returns the chosen folder, or None if
    the user cancelled or no picker could be opened."""
    start = Path(start).expanduser() if start else Path.home()
    if not start.is_dir():
        start = Path.home()

    try:
        if sys.platform == "darwin":
            chosen = _applescript(title, start)
        elif sys.platform == "win32":
            chosen = _winforms(title, start)
        else:
            if not _has_display():
                return None
            chosen = ""
            for helper in _linux_helpers():
                chosen = _linux(title, start, helper)
                if chosen is not None:
                    break  # it ran; "" means the user cancelled, so stop here
    except Exception as e:  # a dialog must never take the app down with it
        debug_log(f"folder picker error: {e}")
        return None

    return Path(chosen) if chosen else None
