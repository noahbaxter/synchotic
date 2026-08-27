"""
Centralized display functions for formatted output.

Any output with color codes or complex formatting belongs here.
Plain text prints can be inlined at the call site.

Usage:
    from src.ui.widgets import display
    display.folder_complete(downloaded, bytes, duration, errors)
"""

from ..primitives.colors import Colors
from ...core.formatting import format_size, format_duration, format_speed

_c = Colors


def _rule_width() -> int:
    """Width for the ━━━ rules, so they span the window instead of a fixed 50."""
    from ..primitives.terminal import get_terminal_width
    return max(50, get_terminal_width() - 4)


# === Network errors ===

def error_offline(message: str):
    print(f"\n{_c.ERROR}Error:{_c.RESET} {message}")
    print("This app requires an internet connection to download charts.")
    print("Please check your connection and try again.\n")

def error_manifest_http(status_code: int):
    print(f"{_c.DIM}Warning: Failed to fetch manifest (HTTP {status_code}){_c.RESET}")

def error_manifest_timeout():
    print(f"{_c.DIM}Warning: Manifest fetch timed out{_c.RESET}")

def error_manifest_generic(error: str):
    print(f"{_c.DIM}Warning: Manifest fetch error: {error}{_c.RESET}")

def error_no_local_manifest():
    print(f"{_c.ERROR}Error:{_c.RESET} Local manifest not found.\n")


# === Auth/OAuth messages ===

def auth_prompt():
    print()
    print("  Sign in with your Google credentials?")
    print()
    print("  Downloads require read-only access.")
    print("  Privacy: https://noahbaxter.dev/synchotic/privacy.html")
    print()
    print("  [Y] Sign in    [N] Not now")
    print()


def auth_opening_browser():
    print("\n  Opening your browser to sign in.")
    print("  If nothing opens, go to the URL printed below.")
    print()


def auth_required_custom_folders():
    print("\n  Please sign in to Google first to add custom folders.")
    print("  Custom folders require access to your Google Drive.")

def auth_required_scan():
    print("\n  Cannot scan custom folders: not signed in to Google.")
    print("  Sign in first to download from custom folders.")

def auth_expired_warning(failure_count: int):
    print()
    print(f"  {failure_count} files failed: your Google sign-in expired.")
    print("  Sign back in to fix these.")
    print()


def session_expired_notice() -> None:
    """The saved sign-in stopped working. Try the obvious fix first."""
    print()
    print("  Your Google sign-in expired.")
    print("  Sign in again from Account, then re-sync.")
    print()


def sign_in_failed_notice() -> None:
    """Sign-in was attempted and did not work, so stop suggesting it."""
    print()
    print("  Couldn't sign you back in.")
    print("  Switch to another download method (rclone or BYOC) from Account.")
    print()


def rclone_consent_explainer() -> None:
    """Explain the one-time rclone consent before opening the browser."""
    print()
    print("  Some charts (large archives) need an authenticated download.")
    print("  Synchotic uses rclone, an established open-source tool, for this.")
    print("  Google's consent screen will say \"rclone\" and request read-only")
    print("  access to your Drive. This is a one-time click.")
    print()

def byoc_not_configured(instructions_path=None, opened: bool = False) -> None:
    """BYOC is selected but no credentials are in place."""
    print()
    print("  This mode requires your own Google credentials, and none are set up.")
    print("  Place your 'credentials.json' in:")
    from ...core.paths import get_data_dir
    print(f"    {get_data_dir()}")
    print()
    print("  If you have trouble, instructions are available in that folder.")
    print("  Want something simpler? Switch to rclone.")
    print()


def library_prompt(current, can_browse: bool = False) -> None:
    print()
    print("  Chart Library")
    print()
    print("  Charts currently live in:")
    print(f"    {current}")
    print()
    print("  Enter a folder to use instead. Markers and staging live inside the")
    print("  library, so moving the folder later takes its state with it.")
    print()
    if can_browse:
        print(f"  {_c.DIM}Press B to browse, or ESC to cancel{_c.RESET}")
    else:
        print(f"  {_c.DIM}Press ESC to cancel{_c.RESET}")
    print()



def library_not_a_folder(path) -> None:
    print(f"\n  Not a folder: {path}\n")


def library_create_failed(path, err) -> None:
    print(f"\n  Could not create {path}")
    print(f"  {err}\n")


def library_is_new(path) -> None:
    print()
    print("  Synchotic has not synced here before, so it looks empty.")
    print("  The next sync will download everything again into this folder.")
    print()


def library_first_run() -> None:
    print()
    print("  Where should your charts live?")
    print(f"  {_c.DIM}Point this at your Clone Hero songs folder. If you used an"
          f" older Synchotic,{_c.RESET}")
    print(f"  {_c.DIM}pick the same folder and your settings and markers come"
          f" across.{_c.RESET}")
    print()


def library_imported(legacy, items) -> None:
    print()
    print(f"  {_c.SUCCESS}Imported your previous setup{_c.RESET} from:")
    print(f"    {legacy}")
    print(f"  {', '.join(items)}")
    print(f"  {_c.DIM}The old folder was left as it was.{_c.RESET}")
    print()


def library_changed(path) -> None:
    print()
    print("  Chart library is now:")
    print(f"    {path}")
    print()


def library_unavailable(path) -> None:
    """The configured library is not reachable, e.g. an unmounted volume."""
    print()
    print("  Library not found:")
    print(f"    {path}")
    print()
    print("  If it lives on an external or network drive, connect it and retry.")
    print("  Nothing has been scanned, downloaded or deleted.")
    print()


def purge_skipped_new_library(path) -> None:
    """First sync at a library we did not create. Explain, delete nothing."""
    print()
    print("  This looks like a library Synchotic has not synced before:")
    print(f"    {path}")
    print()
    print("  Nothing was removed. From the next sync onward, Synchotic manages")
    print("  the folders of drives you enable: anything inside them that is not")
    print("  part of that drive WILL BE DELETED. Folders that are not drives are")
    print("  never touched.")
    print()


def purge_skipped_unowned(folder_name: str) -> None:
    """A disabled drive whose folder we never created. Almost certainly theirs."""
    print(f"  Skipped '{folder_name}': Synchotic did not create this folder, so it")
    print("  will not be emptied. Enable the drive to have Synchotic manage it.")


def rclone_no_browser() -> None:
    """Consent needs a browser and there is not one here."""
    print()
    print("  Large archives need an authenticated download, which requires a")
    print("  one-time browser consent. No browser is available on this machine.")
    print("  Set up your own credentials (docs/byoc.md), or run consent on a")
    print("  desktop session.")
    print()


def report_blocked_summary(needs_auth: int, rate_limited: int) -> None:
    """Distinguish 'needs auth setup' from 'Google rate-limited (retry later)'."""
    if needs_auth:
        print(f"  {needs_auth} file(s) need authenticated download "
              f"(set up once via the prompt).")
    if rate_limited:
        print(f"  {rate_limited} file(s) are rate-limited by Google "
              f"(usually clears within a day; will retry next sync).")


# === Custom folder messages ===

def add_folder_prompt():
    print()
    print("  Add Custom Folder")
    print()
    print("  Paste a Google Drive folder URL or ID.")
    print("  The folder must be shared (anyone with link) or in your Drive.")
    print()
    print("  Example: https://drive.google.com/drive/folders/abc123...")
    print()
    print(f"  {_c.DIM}Press ESC to cancel{_c.RESET}")
    print()

def add_folder_invalid_url(error: str):
    print(f"\n  {_c.BOLD}{error}{_c.RESET}")
    print("  Please use a Google Drive folder link like:")
    print("  https://drive.google.com/drive/folders/abc123...")

def add_folder_access_denied():
    print(f"\n  {_c.BOLD}Could not access folder.{_c.RESET}")
    print("  Make sure the folder is shared or you have access.")

def add_folder_found(folder_name: str):
    print(f"  Found: {_c.BOLD}{folder_name}{_c.RESET}")


# === Scan messages ===

def scan_header(folder_name: str):
    print()
    print("=" * 50)
    print(f"Scanning: {folder_name}")
    print("=" * 50)

def scan_custom_folders_header():
    print()
    print("=" * 50)
    print("Scanning custom folders...")
    print("=" * 50)

def scan_complete_header():
    print()
    print("=" * 50)
    print("Scan complete. Starting download...")
    print("=" * 50)

def scan_folder_header(folder_name: str):
    print(f"\n[{folder_name}]")
    print("-" * 40)

def scan_progress(folders: int, files: int, shortcuts: int = 0):
    from ..primitives import print_progress
    shortcut_info = f", {shortcuts} shortcuts" if shortcuts else ""
    print_progress(f"Scanning... {folders} folders, {files} files{shortcut_info}")

def scanning_folder():
    print(f"  {_c.DIM}Scanning folder...{_c.RESET}")


# === Folder status messages ===

def folder_status_empty(filtered_count: int = 0):
    parts = ["no files"]
    if filtered_count > 0:
        parts.append(f"{_c.DIM}{filtered_count} filtered{_c.RESET}")
    print(f"  {', '.join(parts)}")

def folder_status_synced(file_count: int, filtered_count: int = 0):
    parts = [f"{file_count} files"]
    if filtered_count > 0:
        parts.append(f"{_c.DIM}{filtered_count} filtered{_c.RESET}")
    print(f"  {', '.join(parts)} • {_c.SUCCESS}✓ synced{_c.RESET}")

def folder_synced_inline(header: str, file_count: int, width: int | None = None):
    width = _rule_width() if width is None else width
    name = f"{_c.SUCCESS}✓{_c.RESET} {header} • {file_count} files"
    # Strip ANSI to measure visible length for padding
    from ..components import strip_ansi
    visible = f"━━━ {strip_ansi(name)} "
    pad = max(5, width - len(visible))
    print(f"━━━ {name} {'━' * pad}")


# === Download messages ===

def download_starting(file_count: int, chart_count: int, total_size: int, skipped: int = 0):
    line = f"  Downloading {chart_count} chart{'s' if chart_count != 1 else ''} ({file_count} files, {format_size(total_size)})"
    if skipped > 0:
        line += f" • {skipped} synced"
    print(line)
    print()

def download_cancelled(downloaded: int, complete_charts: int, cleaned: int = 0):
    print(f"  Cancelled. Downloaded {downloaded} files ({complete_charts} complete charts).")
    if cleaned > 0:
        print(f"  Cleaned up {cleaned} partial download(s).")


# === Folder completion summary ===

def folder_complete(downloaded: int, bytes_downloaded: int, duration: float,
                    errors: int = 0, width: int | None = None):
    width = _rule_width() if width is None else width
    from ..components import strip_ansi
    avg_speed = bytes_downloaded / duration if duration > 0 else 0
    content = f"{_c.SUCCESS}✓{_c.RESET} {downloaded} files"
    if bytes_downloaded > 0:
        content += f" ({format_size(bytes_downloaded)})"
    content += f" in {format_duration(duration)}"
    if avg_speed > 0:
        content += f" • {format_speed(avg_speed)}"
    if errors > 0:
        content += f" • {_c.ERROR}{errors} errors{_c.RESET}"
    visible = f"━━━ {strip_ansi(content)} "
    pad = max(5, width - len(visible))
    print(f"━━━ {content} {'━' * pad}")


# === Multi-folder completion summary ===

def sync_cancelled(downloaded: int = 0):
    summary = f"{_c.DIM}Cancelled{_c.RESET}"
    if downloaded > 0:
        summary += f" - {downloaded} files downloaded"
    print(summary)

def sync_complete(downloaded: int, bytes_downloaded: int, duration: float):
    avg_speed = bytes_downloaded / duration if duration > 0 else 0
    summary = f"{_c.SUCCESS}✓{_c.RESET} {downloaded} files"
    if bytes_downloaded > 0:
        summary += f" ({format_size(bytes_downloaded)})"
    summary += f" in {format_duration(duration)}"
    if avg_speed > 0:
        summary += f" • {format_speed(avg_speed)} avg"
    print(summary)

def sync_already_synced():
    print(f"{_c.SUCCESS}✓{_c.RESET} All files synced")

def sync_errors(error_count: int):
    print(f"  {_c.ERROR}{error_count} errors{_c.RESET}")

def sync_rate_limited(count: int):
    print(f"  {_c.DIM}{count} rate-limited{_c.RESET}")

def rate_limit_guidance(folder_names: set[str]):
    print()
    folder_list = ", ".join(sorted(folder_names))
    print(f"  {_c.DIM}[{folder_list}] hit Google's download limit.{_c.RESET}")
    print(f"  {_c.DIM}Run sync again later, or try tomorrow (resets every 24h).{_c.RESET}")


# === Purge messages ===

def purge_drive_disabled(folder_name: str, file_count: int, total_size: int):
    print(f"\n{_c.DIM}[{folder_name}]{_c.RESET} (drive disabled)")
    print(f"  Found {_c.ERROR}{file_count}{_c.RESET} files ({format_size(total_size)})")

def purge_folder(folder_name: str, file_count: int, total_size: int):
    print(f"\n{_c.DIM}[{folder_name}]{_c.RESET}")
    print(f"  Found {_c.ERROR}{file_count}{_c.RESET} files to purge ({format_size(total_size)})")

def purge_tree_lines(lines: list[str], max_lines: int = 5):
    for line in lines[:max_lines]:
        print(f"  {line}")
    if len(lines) > max_lines:
        print(f"    ... and {len(lines) - max_lines} more folders")

def purge_removed(deleted: int, failed: int = 0):
    msg = f"  {_c.ERROR}Removed {deleted} files{_c.RESET}"
    if failed > 0:
        msg += f" ({failed} failed)"
    print(msg)

def purge_partial_downloads(file_count: int, total_size: int):
    print(f"\n{_c.DIM}[Partial Downloads]{_c.RESET}")
    print(f"  Found {_c.ERROR}{file_count}{_c.RESET} incomplete download(s) ({format_size(total_size)})")

def purge_partial_cleaned(deleted: int, failed: int = 0):
    msg = f"  {_c.ERROR}Cleaned up {deleted} file(s){_c.RESET}"
    if failed > 0:
        msg += f" ({failed} failed)"
    print(msg)

def purge_summary(deleted: int, total_size: int, failed: int = 0):
    print(f"{_c.ERROR}✗{_c.RESET} Removed {deleted} files ({format_size(total_size)})")
    if failed > 0:
        print(f"  {_c.DIM}{failed} file(s) could not be deleted{_c.RESET}")

def purge_nothing():
    print(f"{_c.SUCCESS}✓{_c.RESET} No files to purge")


# === Download errors ===

def download_errors_header():
    print()
    print(f"{_c.ERROR}Download errors:{_c.RESET}")

def download_errors_context(context: str, errors: list, show_all: bool = False, sample_size: int = 3):
    if show_all or len(errors) <= sample_size:
        print(f"  {_c.DIM}[{context}]{_c.RESET} {len(errors)} failed:")
        for err in errors:
            print(f"    - {err.filename} ({err.reason})")
    elif len(errors) <= 100:
        print(f"  {_c.DIM}[{context}]{_c.RESET} {len(errors)} failed:")
        for err in errors[:sample_size]:
            print(f"    - {err.filename} ({err.reason})")
        print(f"    ... and {len(errors) - sample_size} more")
    else:
        print(f"  {_c.DIM}[{context}]{_c.RESET} {len(errors)} failed")
