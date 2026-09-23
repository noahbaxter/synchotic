"""Messages printed to the scrollback, outside the full-screen panels. The
words come from copy.py; this adds the colour and the indent."""

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


# === Sync run summary, under the panel it leaves behind ===

def sync_cancelled(downloaded: int = 0):
    summary = f"{_c.DIM}{copy.CANCELLED}.{_c.RESET}"
    if downloaded > 0:
        summary += " " + copy.DOWNLOADED_FILES.format(files=count(downloaded, "file"))
    print(summary)

def sync_complete(downloaded: int, bytes_downloaded: int, duration: float):
    avg_speed = bytes_downloaded / duration if duration > 0 else 0
    summary = f"{_c.SUCCESS}✓{_c.RESET} {count(downloaded, 'file')}"
    if bytes_downloaded > 0:
        summary += f" ({format_size(bytes_downloaded)})"
    summary += " " + copy.DONE_IN.format(time=format_duration(duration))
    if avg_speed > 0:
        summary += " • " + copy.AVG_SPEED.format(speed=format_speed(avg_speed))
    print(summary)

def sync_already_synced():
    print(f"{_c.SUCCESS}✓{_c.RESET} {copy.ALL_SYNCED}")

def sync_failed(reason: str, failed_count: int = 0):
    """Nothing downloaded because scans failed, not because nothing was due."""
    scope = f" ({count(failed_count, 'setlist')})" if failed_count else ""
    print(f"{_c.ERROR}✗{_c.RESET} {copy.SYNC_FAILED.format(reason=reason)}{scope}")

# === Download errors ===

# Raw downloader messages, in words a person can act on. First match wins, so
# specific patterns come first; a full disk or a lost connection can arrive
# inside another failure's message.
_FAILURE_WORDS = (
    ("no space left", copy.FAIL_DISK_FULL),
    ("errno 28", copy.FAIL_DISK_FULL),
    ("cannot connect", copy.FAIL_OFFLINE),
    ("connection reset", copy.FAIL_OFFLINE),
    ("nodename nor servname", copy.FAIL_OFFLINE),
    ("needs auth", copy.FAIL_NEEDS_SIGN_IN),
    ("rate limited", copy.FAIL_RATE_LIMITED),
    ("http 403", copy.FAIL_RATE_LIMITED),
    ("http 429", copy.FAIL_RATE_LIMITED),
    ("http 401", copy.FAIL_SIGNED_OUT),
    ("timeout", copy.FAIL_TIMED_OUT),
    ("bytes)", copy.FAIL_CUT_SHORT),
    ("http 404", copy.FAIL_GONE),
    ("http 5", copy.FAIL_DRIVE_ERROR),
    ("unsupported archive", copy.FAIL_FORMAT),
    ("extract", copy.FAIL_UNPACK),
)

# What to do about each, including "nothing to fix" where that is the answer.
ADVICE = {
    copy.FAIL_DISK_FULL: copy.ADVICE_DISK_FULL,
    copy.FAIL_OFFLINE: copy.ADVICE_OFFLINE,
    copy.FAIL_NEEDS_SIGN_IN: copy.ADVICE_NEEDS_SIGN_IN,
    copy.FAIL_SIGNED_OUT: sentences(copy.STATUS_SIGNIN_EXPIRED, copy.FIX_SIGN_IN),
    copy.FAIL_RATE_LIMITED: sentences(copy.ADVICE_RATE_LIMITED, copy.RETRIES_NEXT_SYNC),
    copy.FAIL_TIMED_OUT: sentences(copy.RETRIES_NEXT_SYNC, copy.NOTHING_TO_FIX),
    copy.FAIL_CUT_SHORT: sentences(copy.ADVICE_CUT_SHORT, copy.RETRIES_NEXT_SYNC),
    copy.FAIL_GONE: sentences(copy.ADVICE_GONE, copy.NOTHING_TO_FIX),
    copy.FAIL_DRIVE_ERROR: sentences(copy.ADVICE_DRIVE_ERROR, copy.RETRIES_NEXT_SYNC),
    copy.FAIL_FORMAT: sentences(copy.ADVICE_FORMAT, copy.NOTHING_TO_FIX),
    copy.FAIL_UNPACK: sentences(copy.ADVICE_UNPACK, copy.REPORT_IT),
    copy.FAIL_UNKNOWN: sentences(copy.ADVICE_UNKNOWN, copy.RETRIES_NEXT_SYNC),
}

# Reasons nothing will fix until someone does something.
NEEDS_YOU = frozenset({copy.FAIL_DISK_FULL, copy.FAIL_OFFLINE,
                       copy.FAIL_NEEDS_SIGN_IN, copy.FAIL_SIGNED_OUT})

# Reasons that clear up on their own, or where there is nothing to fix. Anything
# in neither set is unexplained, which is the case worth reporting.
SORTS_ITSELF_OUT = frozenset({copy.FAIL_RATE_LIMITED, copy.FAIL_TIMED_OUT,
                              copy.FAIL_CUT_SHORT, copy.FAIL_DRIVE_ERROR,
                              copy.FAIL_GONE, copy.FAIL_FORMAT, copy.FAIL_UNKNOWN})

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
            return tone, reason, ADVICE.get(reason, sentences(copy.REPORT_IT))
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
    return copy.FAIL_UNKNOWN


def failure_summary(by_reason: dict) -> None:
    """What failed and why, grouped, under the frame the sync just left."""
    total = sum(len(errors) for errors in by_reason.values())
    print()
    print(f"  {_c.ERROR}{copy.DID_NOT_DOWNLOAD.format(charts=count(total, 'chart'))}{_c.RESET}")
    for reason, errors in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"    {len(errors)} {reason}")
        for err in errors[:3]:
            context = f"{_c.DIM}[{err.path_context}]{_c.RESET} " if err.path_context else ""
            print(f"      {context}{err.filename}")
        if len(errors) > 3:
            print(f"      {_c.MUTED}{copy.AND_MORE.format(n=len(errors) - 3)}{_c.RESET}")
        advice = ADVICE.get(reason)
        if advice:
            print(f"      {_c.MUTED}{advice}{_c.RESET}")
    print()
