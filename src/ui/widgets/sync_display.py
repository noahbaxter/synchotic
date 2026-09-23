"""
Centralized display functions for formatted output.

Any output with color codes or complex formatting belongs here.
Plain text prints can be inlined at the call site.

Usage:
    from src.ui.widgets import display
    display.folder_complete(downloaded, bytes, duration, errors)
"""

from ... import copy
from ..primitives.colors import Colors
from ...core.formatting import count, format_size, format_duration, format_speed

_c = Colors


def sentences(*parts: str) -> str:
    """Join copy strings as sentences, adding a full stop to any that end
    without punctuation, so a shared fragment works on its own or in a line."""
    return " ".join(p if p[-1:] in ".!?:" else p + "." for p in parts if p)


def _say(text: str, indent: str = "  ") -> None:
    """Print a copy string at the scrollback's indent, every line of it:
    copy.py keeps layout out of its strings."""
    for line in text.split("\n"):
        print(f"{indent}{line}" if line else "")


def _rule_width() -> int:
    """Width for the ━━━ rules, so they span the window instead of a fixed 50."""
    from ..primitives.terminal import get_terminal_width
    return max(50, get_terminal_width() - 4)


# === Auth/OAuth messages ===

def auth_prompt():
    print()
    print(f"  {copy.SIGNIN_QUESTION}")
    print()
    print(f"  {copy.SIGNIN_SCOPE}")
    print(f"  {copy.SIGNIN_PRIVACY}")
    print()
    print(f"  {copy.SIGNIN_KEYS}")
    print()


def auth_opening_browser():
    print()
    _say(copy.SIGNIN_OPENING)
    print()


def _blocked(line: str, reason: str, where: str) -> None:
    print(f"\n  {line.format(reason=reason)}")
    print(f"  {copy.FIX_FROM.format(where=where)}")


def sync_blocked(reason: str):
    """Sync cannot start because the chosen download mode is not usable."""
    _blocked(copy.SYNC_BLOCKED, reason, copy.SETTINGS_MODE)


def library_blocked(reason: str):
    """No library to scan into. Points at the library row, not Account:
    nothing about the mode is wrong here."""
    _blocked(copy.SCAN_BLOCKED, reason, copy.SETTINGS_LOCATION)


def custom_folder_blocked(reason: str):
    _blocked(copy.ADD_BLOCKED, reason, copy.SETTINGS_MODE)


def auth_expired_warning(failure_count: int):
    print()
    print(f"  {sentences(count(failure_count, 'file') + ' failed', copy.STATUS_SIGNIN_EXPIRED)}")
    print(f"  {copy.FIX_SIGN_IN}")
    print()


def session_expired_notice() -> None:
    """The saved sign-in stopped working. Try the obvious fix first."""
    print()
    _say(copy.SIGNIN_EXPIRED)
    print()


def rclone_consent_explainer() -> None:
    """One line before the browser opens. The mode screen already explained
    why; the only new fact is that Google's screen will say "rclone"."""
    print()
    _say(copy.RCLONE_CONSENT)
    print()


def byoc_not_configured() -> None:
    """BYOC is selected but no credentials are in place. The path is always
    printed: with no file manager the folder never pops up."""
    from ...core.paths import get_data_dir

    print()
    print(f"  {copy.BYOC_STEPS}")
    print(f"    {get_data_dir()}")
    print()


def setup_frame(question: str, body: str, setup_step=None, step_name="") -> tuple:
    """(box title, subtitle) for one screen. Inside setup the box is headed
    FIRST TIME SETUP with "Chart Library - 1/3" under it, so the steps read
    as one sequence, and the question moves to just above the answers."""
    if not setup_step:
        return question, body

    # (step, total) or (step, total, title): a repair launch is headed as
    # setup, not as a first run.
    step, total, *title = setup_step
    parts = [f"{step_name or question} - {step}/{total}"]
    if body:
        parts.append(body)
    # A screen whose options are the answer passes "" and has none.
    if question and step_name and question != step_name:
        parts.append(question)
    return (title[0] if title else copy.SETUP_TITLE), "\n\n".join(parts)


def library_not_a_folder(path) -> None:
    print(f"\n  {copy.FOLDER_NOT_A_FOLDER.format(path=path)}\n")


def library_create_failed(err) -> None:
    """The OS error names the path and why, so it is the whole message."""
    print(f"\n  {copy.FAILURE}: {err}\n")


def library_not_empty(path, chart_folders: int, files: int, folders: int,
                      more: bool = False) -> str:
    """A folder with things in it Synchotic did not put there. Returned, not
    printed: a menu comes next and repaints the screen."""
    return f"{path}\n\n" + copy.FOLDER_NOT_EMPTY.format(
        counts=_counts(chart_folders, files, folders, more),
        warning=deletion_warning(files, more))


def deletion_warning(files: int = 0, more: bool = False) -> str:
    """The one warning, coloured. No count for a folder of empty folders:
    "all 0 files" reads as nothing at stake, and the folders still go."""
    what = (copy.DELETION_ALL.format(files=count(files, "unmanaged file", more))
            if files else copy.DELETION_ANY)
    return copy.DELETION_WARNING.format(warn_open=_c.ERROR,
                                        warn_close=_c.RESET, what=what)


def _counts(chart_folders: int, files: int, folders: int, more: bool) -> str:
    parts = [count(chart_folders, "chart folder", more)] if chart_folders else []
    parts += [count(files, "file", more), count(folders, "folder", more)]
    return ", ".join(parts)


def library_contents(contents) -> str:
    """Drives in a library under their group headings, in home screen order.
    `contents` is (group, name, setlist count)."""
    lines, current = [], None
    for group, name, setlists in contents:
        heading = (group or copy.GROUP_OTHER).upper()
        if heading != current:
            if lines:
                lines.append("")
            # Dimmed, so a heading reads differently from the drives under it.
            lines.append(f"{_c.MUTED_DIM}{heading}{_c.RESET}")
            current = heading
        lines.append(copy.DRIVE_LINE.format(
            name=name, setlists=count(setlists, "setlist")))
    return "\n".join(lines)


def library_summary(path, *, chart_folders: int, files: int, folders: int,
                    more: bool, drive_matches=(), has_markers: bool = False,
                    contents=()) -> tuple:
    """(question, body, risky) for the folder somebody just picked. `risky`
    is true when a sync would delete what is in it, and puts the cursor on
    No."""
    where = f"{path}\n\n"
    listing = f"\n\n{library_contents(contents)}" if contents else ""

    if has_markers or drive_matches:
        return (copy.CONFIRM_Q, where + copy.KNOWN_LIBRARY + listing, False)

    # Anything in here that is not ours gets deleted on sync, charts or not.
    if files or folders:
        return (copy.CONFIRM_RISKY_Q,
                library_not_empty(path, chart_folders, files, folders, more),
                True)

    return (copy.CONFIRM_Q, where + copy.FOLDER_IS_NEW, False)


def library_unavailable(path) -> None:
    """The configured library is not reachable, e.g. an unmounted volume."""
    print()
    print(f"  {copy.LIBRARY_MISSING}:")
    print(f"    {path}")
    print()
    print(f"  {copy.FIX_RECONNECT}")
    print(f"  {copy.NOTHING_CHANGED}")
    print()


def library_lost(path) -> None:
    """The library went away mid-run. Unlike library_unavailable, this cannot
    promise nothing has happened yet."""
    print()
    print(f"  {copy.LIBRARY_MISSING}:")
    print(f"    {path}")
    print()
    print(f"  {sentences(copy.STOPPED_MIDWAY, copy.FIX_RECONNECT)}")
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
    _say(copy.NO_BROWSER)
    print()


# === Custom folder messages ===

def add_folder_prompt():
    print()
    print(f"  {copy.ROW_ADD_CUSTOM}")
    print()
    _say(copy.ADD_HOWTO)
    print()
    print(f"  {copy.ADD_EXAMPLE}")
    print()
    print(f"  {_c.DIM}{copy.ESC_TO_CANCEL}{_c.RESET}")
    print()

def add_folder_invalid_url(error: str):
    print(f"\n  {_c.BOLD}{error}{_c.RESET}")
    _say(copy.URL_USE_FOLDER_LINK)

def add_folder_failed(error: str):
    """Google's own reason, not a guess at what is wrong with the folder."""
    print(f"\n  {_c.BOLD}{copy.FAILURE}:{_c.RESET} {error}")

def add_folder_found(folder_name: str):
    print(f"  {copy.ADD_FOUND.format(bold_open=_c.BOLD, bold_close=_c.RESET, name=folder_name)}")


# === Scan messages ===

def scan_header(folder_name: str):
    print()
    print("=" * 50)
    print(copy.SCAN_TITLE.format(name=folder_name))
    print("=" * 50)

def scan_progress(folders: int, files: int):
    from ..primitives import print_progress
    print_progress(copy.SCAN_PROGRESS.format(folders=folders, files=files))


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

def sync_failed(reason: str, failed_count: int = 0):
    """Nothing downloaded because scans failed, not because nothing was due."""
    scope = f" ({failed_count} setlist{'s' if failed_count != 1 else ''})" if failed_count else ""
    print(f"{_c.ERROR}✗{_c.RESET} Sync failed because {reason}{scope}")

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

# Raw downloader messages, in words a person can act on. First match wins, so
# specific patterns come first; a full disk or a lost connection can arrive
# inside another failure's message.
_FAILURE_WORDS = (
    ("no space left", "disk full"),
    ("errno 28", "disk full"),
    ("cannot connect", "no connection"),
    ("connection reset", "no connection"),
    ("nodename nor servname", "no connection"),
    ("needs auth", "needs sign-in"),
    ("rate limited", "rate limited"),
    ("http 403", "rate limited"),
    ("http 429", "rate limited"),
    ("http 401", "signed out"),
    ("timeout", "timed out"),
    ("bytes)", "cut short"),
    ("http 404", "not on Drive"),
    ("http 5", "Drive error"),
    ("unsupported archive", "unknown format"),
    ("extract", "unpack failed"),
)

# What to do about each, including "nothing to fix" where that is the answer.
ADVICE = {
    "disk full": "Free up space on the drive holding your library, then sync again.",
    "no connection": "Check your internet, then sync again.",
    # Mode, not sign-in: the sign-in row is greyed out in rclone mode.
    "needs sign-in": "Settings → Account → Mode: connect rclone, or set up your "
                     "own credentials.",
    "signed out": "Your Google sign-in expired. Sign in again from Account.",
    "rate limited": "Google throttled the drive. Usually clears within a day; "
                    "the next sync retries them.",
    "timed out": "The next sync retries these. Nothing to fix.",
    "cut short": "Usually a throttle in disguise. The next sync retries these.",
    "not on Drive": "These were removed upstream. The next scan drops them. "
                    "Nothing to fix.",
    "Drive error": "Google's end, not yours. The next sync retries these.",
    "unknown format": "Not a format Clone Hero reads. Nothing to fix.",
    "unpack failed": "The archive would not open. Report it if it keeps happening.",
    "failed": "No cause reported. The next sync retries these.",
}

# Reasons nothing will fix until someone does something.
NEEDS_YOU = frozenset({"disk full", "no connection", "needs sign-in", "signed out"})

# Reasons that clear up on their own, or where there is nothing to fix. Anything
# in neither set is unexplained, which is the case worth reporting.
SORTS_ITSELF_OUT = frozenset({"rate limited", "timed out", "cut short", "Drive error",
                              "not on Drive", "unknown format", "failed"})

FIX = "fix"
REPORT = "report"
TRANSIENT = "transient"


def advise(reasons: list[str]) -> tuple[str, str, str]:
    """What to do about this run's failures, as (tone, reason, advice): the
    most pressing reason present. Something that needs doing beats something
    nobody can explain, which beats something that will pass."""
    if not reasons:
        return "", "", ""
    tally: dict[str, int] = {}
    for reason in reasons:
        tally[reason] = tally.get(reason, 0) + 1

    def most(pool):
        return max(pool, key=lambda r: tally[r]) if pool else None

    needs_you = [r for r in tally if r in NEEDS_YOU]
    unexplained = [r for r in tally if r not in NEEDS_YOU and r not in SORTS_ITSELF_OUT]
    passing = [r for r in tally if r in SORTS_ITSELF_OUT]

    for tone, pool in ((FIX, needs_you), (REPORT, unexplained), (TRANSIENT, passing)):
        reason = most(pool)
        if reason:
            return tone, reason, ADVICE.get(reason, "Report it if it keeps happening.")
    return "", "", ""


def describe_failure(message: str) -> str:
    """One short reason for a failed chart, from a downloader message written
    for a log."""
    lowered = message.lower()
    for pattern, reason in _FAILURE_WORDS:
        if pattern in lowered:
            return reason

    # Unrecognised: the parenthetical is the closest thing to a cause, and a
    # raw cause beats a vague stand-in.
    if "(" in message and ")" in message:
        return message[message.index("(") + 1:message.index(")")]
    return "failed"


def blocked_outcome(recovered: int, still_blocked: int, mode: str = "rclone") -> None:
    """Report charts Google would not serve anonymously, once the retry has
    run, and only about what actually happened."""
    if recovered:
        print(f"  {_c.SUCCESS}✓{_c.RESET} {recovered} large chart(s) downloaded "
              f"through rclone")
    if not still_blocked:
        return

    print(f"  {_c.ERROR}{still_blocked} chart(s) need an authenticated "
          f"download{_c.RESET}")
    if mode == "rclone":
        print(f"  {_c.MUTED}rclone already tried these. The next sync retries "
              f"them; if they keep failing, set up your own credentials."
              f"{_c.RESET}")
    else:
        print(f"  {_c.MUTED}Settings → Account → Mode: connect rclone, "
              f"then sync again.{_c.RESET}")


def failure_summary(by_reason: dict) -> None:
    """What failed and why, grouped, under the frame the sync just left."""
    total = sum(len(errors) for errors in by_reason.values())
    print()
    print(f"  {_c.ERROR}{total} chart(s) did not download{_c.RESET}")
    for reason, errors in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"    {len(errors)} {reason}")
        for err in errors[:3]:
            context = f"{_c.DIM}[{err.path_context}]{_c.RESET} " if err.path_context else ""
            print(f"      {context}{err.filename}")
        if len(errors) > 3:
            print(f"      {_c.MUTED}and {len(errors) - 3} more{_c.RESET}")
        advice = ADVICE.get(reason)
        if advice:
            print(f"      {_c.MUTED}{advice}{_c.RESET}")
    print()
