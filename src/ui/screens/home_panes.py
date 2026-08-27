"""
Two-pane home screen.

Left pane is the drive list, with group names demoted to section headers. Right
pane is whatever the left cursor sits on: a drive's setlists, or the settings
list. That folds in the drill-down that used to be drive_config.py -- toggling a
setlist and watching its drive's totals move now happen on one screen instead of
two.

Sync and Quit are keys rather than rows (S and Esc). Their live state moves to
the footer, which TwoPane recomputes every frame, so the sync delta and the scan
progress stay visible from every row instead of only when you scroll to them.

Returns the same ``(action, value, position)`` triple the one-column menu did,
so sync.py's dispatch loop is unchanged. Setlist and drive toggles never return:
they mutate settings and refresh the cache in place, because leaving the screen
to apply a toggle is the thing this layout exists to stop doing.
"""

import shutil
from pathlib import Path

from chotic_ui.widgets.two_pane import TwoPane
from chotic_ui.primitives.terminal import visible_len, truncate_ansi

from src.config import UserSettings, DrivesConfig
from src.core.formatting import sort_by_name, format_duration, format_size
from src.sync import get_persistent_stats_cache, compute_setlist_stats
from src.sync.archive_charts import effective_chart_count, forced_counts
from ..primitives import Colors
from ..components import strip_ansi, format_setlist_item
from .home import (
    MainMenuCache, compute_main_menu_cache, update_menu_cache_on_toggle,
    _get_setlist_names,
)


# Left-pane values. A drive row carries its folder id; the tail rows carry an
# action the right pane will offer.
def _drive(folder_id):
    return ("drive", folder_id)


SETTINGS = ("settings", None)

LEFT_WIDTH = 38

# Which pane you were in and where the cursor sat, remembered across a trip to
# another screen. sync.py rebuilds this screen from scratch every time it comes
# back, so without this, pressing Esc in Add folder or the library picker drops
# you on the left pane at the top -- nowhere near the row you were working on.
_LAST = {"focus": "left", "right_cursor": 0, "right_scroll": 0, "left_value": None}


def forget_pane_state() -> None:
    """Drop the remembered position, e.g. when the drive list changes shape."""
    _LAST.update(focus="left", right_cursor=0, right_scroll=0, left_value=None)


def _right_text_width() -> int:
    """Usable characters in a right-pane row, mirroring TwoPane's own frame
    maths so the stat column can be flushed to the pane's edge."""
    cols = shutil.get_terminal_size((100, 34))[0]
    w = max(72, min(cols - 2, 110))
    return max(20, (w - 4) - LEFT_WIDTH - 3 - 2)


# Right-pane columns. Fixed widths so every row's numbers line up in the same
# place instead of drifting with the length of the name beside them.
CHARTS_W, SIZE_W, CHANGE_W = 7, 10, 11
# Left-pane columns.
LEFT_CHANGE_W = 9


def _cell(text: str, width: int, color: str = "") -> str:
    """Right-align `text` in a fixed column, measuring what is actually visible
    so ANSI codes do not shove the column out of true. Over-long values are cut
    to the column: letting one row run wide pushed the whole line past the pane,
    and the frame's own truncation then replaced the last cell with an ellipsis."""
    text = text or ""
    if visible_len(text) > width:
        text = truncate_ansi(text, width)
    pad = max(0, width - visible_len(text))
    body = f"{color}{text}{Colors.RESET}" if color and text else text
    return " " * pad + body


def _columns(head: str, cells, width: int) -> str:
    """`head` flush left, `cells` as fixed right-aligned columns at the far edge."""
    tail = "".join(_cell(t, w, c) for t, w, c in cells)
    tail_w = sum(w for _, w, _ in cells)
    room = width - tail_w - 1
    if visible_len(head) > room:
        head = truncate_ansi(head, max(1, room))
    gap = width - visible_len(head) - tail_w
    return f"{head}{' ' * max(1, gap)}{tail}"


def _plain_delta(delta: str) -> str:
    """Deltas arrive wrapped for inline use ("[+22.9 MB]"); in a column of their
    own the brackets are just noise."""
    return strip_ansi(delta or "").strip().strip("[]").strip()


def _sync_label(cache: MainMenuCache) -> str:
    """What Sync will do, for the footer: a tick when there is nothing to fetch,
    otherwise the size of what is missing."""
    if cache.sync_checkmark:
        return f"{Colors.SUCCESS}\u2713{Colors.RESET} synced"
    if cache.sync_delta:
        return f"sync {cache.sync_delta}"
    return "sync"


def _copy_cache(dst: MainMenuCache, src: MainMenuCache) -> None:
    """Refresh in place: sync.py holds a reference to this object."""
    for f in ("subtitle", "sync_action_desc", "sync_delta", "sync_checkmark",
              "folder_stats", "folder_deltas", "folder_checkmarks", "folder_states",
              "folder_scan_progress", "group_enabled_counts"):
        setattr(dst, f, getattr(src, f))


def _row(text, value, selectable=True):
    """TwoPane wants (render(focused, cursor) -> str, value, selectable). Nothing
    here varies with focus; the widget owns the cursor marker."""
    return (lambda focused, cursor: text, value, selectable)


def _header_row(label):
    """Flush against the left edge while the rows under it are indented, so the
    grouping reads at a glance without a count to decode."""
    return _row(f"{Colors.BOLD}{Colors.PRIMARY}{label.upper()}{Colors.RESET}", None, False)


def _spacer():
    return _row("", None, False)


def _rule(width: int):
    """A drawn divider, not a blank line: Settings is a different kind of thing
    from the drives above it and the gap alone did not say so."""
    return _row(f"{Colors.BORDER}{'─' * max(1, width)}{Colors.RESET}", None, False)


def _mode_blocked_reason(user_settings, auth, rclone_connected) -> str:
    """Menu wording for the shared rule in download_mode.mode_blocked_reason.

    The row has a label beside it, so it reads as an instruction ("Sign in
    first") where the sync summary needs a clause ("...because you are not
    signed in").
    """
    from .download_mode import mode_blocked_step

    return {
        "rclone": "Connect rclone first",
        "byoc_setup": "Needs your Google credentials",
        "signin": "Sign in first",
    }.get(mode_blocked_step(user_settings, auth, rclone_connected), "")


def show_main_menu_panes(
    folders: list,
    user_settings: UserSettings = None,
    selected_index: int = 0,
    download_path: Path = None,
    drives_config: DrivesConfig = None,
    cache: MainMenuCache = None,
    auth=None,
    background_scanner=None,
    folder_stats_cache=None,
) -> tuple[str, str | int | None, int]:
    if cache is None:
        cache = compute_main_menu_cache(
            folders, user_settings, download_path, drives_config,
            background_scanner=background_scanner,
        )

    folder_lookup = {f.get("folder_id", ""): f for f in folders}
    persistent = get_persistent_stats_cache()
    # Read once for the life of the screen rather than per row per frame.
    forced = forced_counts()
    # Setlist stats are computed once per drive, not per frame: right_rows runs
    # on every repaint and compute_setlist_stats walks the disk.
    warmed: set[str] = set()

    def _setlists(folder):
        return sort_by_name(_get_setlist_names(folder, background_scanner))

    # ---- left pane ----

    def _drive_label(folder, indent):
        folder_id = folder.get("folder_id", "")
        name = folder.get("name", "")
        state = cache.folder_states.get(folder_id, "current")
        delta = cache.folder_deltas.get(folder_id, "")
        enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True

        dot = f"{Colors.SUCCESS}●{Colors.RESET}" if enabled else f"{Colors.MUTED_DIM}○{Colors.RESET}"
        body = name if enabled else f"{Colors.MUTED_DIM}{name}{Colors.RESET}"
        if state == "scanning":
            body = f"{Colors.ITALIC}{body}{Colors.RESET}"

        head = f"{'  ' if indent else ''}{dot} {body}"

        change = _plain_delta(delta)
        if not change:
            # No column to reserve, so give the name the whole row rather than
            # truncating it to make room for nothing.
            return truncate_ansi(head, LEFT_WIDTH - 2)
        tint = Colors.SUCCESS if change.startswith("+") else Colors.ERROR
        return _columns(head, [(change, LEFT_CHANGE_W, tint)], LEFT_WIDTH - 2)

    def left_rows():
        rows = []
        seen = set()

        def add(folder, indent=False):
            fid = folder.get("folder_id", "")
            if fid in seen:
                return
            seen.add(fid)
            rows.append(_row(_drive_label(folder, indent), _drive(fid)))

        if drives_config:
            for drive in drives_config.get_ungrouped_drives():
                folder = folder_lookup.get(drive.folder_id)
                if folder:
                    add(folder)

            for group_name in drives_config.get_groups():
                group_drives = drives_config.get_drives_in_group(group_name)
                rows.append(_header_row(group_name))
                for drive in group_drives:
                    folder = folder_lookup.get(drive.folder_id)
                    if folder:
                        add(folder, indent=True)

        for folder in folders:
            add(folder)

        rows.append(_rule(LEFT_WIDTH - 2))
        rows.append(_row(f"{Colors.PRIMARY}⚙{Colors.RESET}  Settings", SETTINGS))
        return rows

    # ---- right pane: a drive's setlists ----

    def _warm(folder, setlists):
        folder_id = folder.get("folder_id", "")
        if folder_id in warmed or not download_path or not folder.get("files"):
            return
        dirty = False
        for name in setlists:
            if not persistent.get_setlist(folder_id, name):
                persistent.set_setlist(
                    folder_id, name,
                    compute_setlist_stats(folder, name, download_path, user_settings),
                )
                dirty = True
        if dirty:
            persistent.save()
        warmed.add(folder_id)

    def _setlist_row(folder_id, name, drive_enabled, delta_mode):
        enabled = user_settings.is_subfolder_enabled(folder_id, name)
        cached = persistent.get_setlist(folder_id, name)

        if background_scanner and background_scanner.is_setlist_scanned(folder_id, name):
            state = "current"
        elif background_scanner and background_scanner.is_scanning(folder_id):
            state = "scanning"
        else:
            state = "cached" if cached else "current"

        total_charts = cached.total_charts if cached else 0
        total_size = cached.total_size if cached else 0
        synced_charts = cached.synced_charts if cached else 0
        synced_size = cached.synced_size if cached else 0
        disk_files = cached.disk_files if cached else 0
        disk_size = cached.disk_size if cached else 0
        disk_charts = cached.disk_charts if cached else 0

        fully_synced = synced_charts == total_charts and total_charts > 0
        purge_files = purge_size = purge_charts = missing = 0
        if drive_enabled:
            if not enabled and disk_files > 0:
                purge_files, purge_size, purge_charts = disk_files, disk_size, disk_charts
            if enabled and not fully_synced:
                missing = total_charts - synced_charts

        columns, delta, check = format_setlist_item(
            total_charts=total_charts, synced_charts=synced_charts,
            total_size=total_size, synced_size=synced_size,
            purgeable_files=purge_files, purgeable_charts=purge_charts,
            purgeable_size=purge_size, missing_charts=missing,
            disabled=not enabled or not drive_enabled,
            delta_mode=delta_mode, state=state, disk_size=disk_size,
        )

        off = not enabled or not drive_enabled
        dot = f"{Colors.MUTED_DIM}○{Colors.RESET}" if off else f"{Colors.SUCCESS}●{Colors.RESET}"
        body = f"{Colors.MUTED_DIM}{name}{Colors.RESET}" if off else name
        if state == "scanning":
            body = f"{Colors.ITALIC}{body}{Colors.RESET}"

        # Three columns that each answer one question: how much of it do I have,
        # how big is it, and what will Sync do to it.
        shown_charts = effective_chart_count(
            name, total_charts, disk_charts,
            drive_name=folder_lookup.get(folder_id, {}).get("name", ""),
            forced=forced,
        )
        charts = f"{shown_charts}" if shown_charts else ""
        size = format_size(total_size) if total_size else ""
        change = _plain_delta(delta)
        change_tint = (Colors.SUCCESS if change.startswith("+")
                       else Colors.ERROR if change else "")

        label = _columns(
            f"{dot} {body}",
            [(charts, CHARTS_W, Colors.MUTED),
             (size, SIZE_W, Colors.MUTED),
             (change, CHANGE_W, change_tint)],
            _right_text_width(),
        )
        return _row(label, ("setlist", folder_id, name))

    def _drive_right(folder_id):
        folder = folder_lookup.get(folder_id)
        if not folder:
            return []
        setlists = _setlists(folder)
        _warm(folder, setlists)
        drive_enabled = user_settings.is_drive_enabled(folder_id) if user_settings else True
        delta_mode = user_settings.delta_mode if user_settings else "size"

        rows = [_setlist_row(folder_id, n, drive_enabled, delta_mode) for n in setlists]
        rows.append(_spacer())
        rows.append(_row(f"  {Colors.PRIMARY}Enable all{Colors.RESET}", ("enable_all", folder_id, None)))
        rows.append(_row(f"  {Colors.PRIMARY}Disable all{Colors.RESET}", ("disable_all", folder_id, None)))
        if folder.get("is_custom"):
            rows.append(_spacer())
            label = "Re-scan folder" if folder.get("files") else "Scan folder"
            # A scan with nowhere to write is greyed with the reason beside
            # it, rather than left as a row that ignores you.
            from ...core.paths import library_blocked_reason
            lib_blocked = library_blocked_reason(user_settings)
            if lib_blocked:
                rows.append(_row(f"  {Colors.MUTED_DIM}{label}  ({lib_blocked}){Colors.RESET}",
                                 ("scan_folder", folder_id, None), False))
            else:
                rows.append(_row(f"  {label}", ("scan_folder", folder_id, None)))
            rows.append(_row(f"  {Colors.ERROR}Remove folder{Colors.RESET}", ("remove_folder", folder_id, None)))
        return rows

    # ---- right pane: settings ----

    def _sign_in_option():
        """Sign-in has four states and only one of them is a plain "sign in".

        Embedded OAuth is dead, so a signed-out user with no credentials of
        their own cannot sign in at all -- that used to mean hiding the row,
        which left people hunting for a control that was never there. It is
        shown greyed with the reason instead.
        """
        from ...drive.auth import has_custom_client_config
        from ...config.settings import DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_RCLONE

        mode = (user_settings.download_mode if user_settings else "") or DOWNLOAD_MODE_RCLONE
        if mode == DOWNLOAD_MODE_ANONYMOUS:
            return ("Sign in", "Not used in anonymous mode", ("act", "signin"), False)
        if auth is not None and getattr(auth, "session_expired", False):
            return ("Sign in again", "Restores fast downloads", ("act", "signin"), True)
        if auth is not None and getattr(auth, "is_signed_in", False):
            email = getattr(auth, "user_email", "")
            return ("Sign out", email or "Signed in to Google", ("act", "signout"), True)
        if has_custom_client_config():
            return ("Sign in to Google", "Uses the credentials you set up",
                    ("act", "signin"), True)
        if mode == DOWNLOAD_MODE_RCLONE:
            # rclone downloads through its own remote, so a Google sign-in buys
            # nothing. Saying "Needs your own credentials" read as an unmet
            # requirement in the mode that is actually recommended.
            return ("Sign in", "Not needed in rclone mode", ("act", "signin"), False)
        return ("Sign in", "Needs your own credentials", ("act", "signin"), False)

    def _settings_right():
        from .account import account_status
        from ...core.paths import get_library_path, library_blocked_reason

        def opt(label, value, action, selectable=True):
            """An option the cursor cannot land on is drawn grey throughout, so
            it reads as unavailable rather than as a row that ignores you."""
            pad = " " * max(1, 18 - len(label))
            if selectable:
                text = f"  {Colors.MUTED}{label}{Colors.RESET}{pad}{value}"
            else:
                text = (f"  {Colors.MUTED_DIM}{label}{pad}"
                        f"{strip_ansi(str(value))}{Colors.RESET}")
            return _row(text, action, selectable)

        scanning = bool(background_scanner and not background_scanner.is_done())
        signed_out = not (auth and getattr(auth, "is_signed_in", False))

        rclone_connected = False
        try:
            import src.rclone as rclone
            rclone_connected = rclone.is_authed()
        except Exception:
            rclone_connected = False

        # Anything that talks to Drive is offered only when the chosen mode can
        # actually reach it. Gating on sign-in instead would be wrong: anonymous
        # mode has no token by design and still resolves public folders on the
        # API key alone, so it would block a setup that works.
        mode_blocked = _mode_blocked_reason(user_settings, auth, rclone_connected)

        # A library that is unset or unmounted blocks the same work, but not
        # the row that fixes it: Location stays reachable either way.
        lib_blocked = library_blocked_reason(user_settings)
        blocked = mode_blocked or lib_blocked

        if blocked:
            rescan = blocked
        elif scanning:
            rescan = "Scanning…"
        else:
            rescan = "Force re-scan all drives"

        sign_label, sign_value, sign_action, sign_ok = _sign_in_option()

        return [
            _header_row("Account"),
            # download_mode, under the name the chooser it opens already uses.
            # The value reports whether that mode can actually download, not
            # just which one is set: a mode that cannot is the thing worth
            # seeing without opening anything.
            opt("Mode", account_status(user_settings, auth, rclone_connected),
                ("act", "download_mode")),
            opt(sign_label, sign_value, sign_action, sign_ok),
            _spacer(),
            _header_row("Library"),
            # Changing it rescans the new location, so it fails the same way
            # a rescan does -- except when the library itself is the problem,
            # which is what this row exists to fix.
            opt("Location", mode_blocked or lib_blocked or str(get_library_path()),
                ("act", "library"), selectable=not mode_blocked),
            # Opens a local folder, so it works with no Drive access at all.
            opt("Open folder", "Settings, logs, credentials", ("act", "open_data_folder")),
            _spacer(),
            _header_row("Drives"),
            # Resolving a folder is a Drive call: without a working mode it
            # only ever reaches "access denied", several screens in.
            opt("Add folder", mode_blocked or "Your own Google Drive folder",
                ("act", "add_custom"), selectable=not mode_blocked),
            # A rescan with no working mode or no library to write into
            # returns before doing any work, and one during a scan has nothing
            # to add, so none of the three is offerable.
            opt("Rescan", rescan, ("act", "rescan"),
                selectable=not (blocked or scanning)),
        ]

    def _download_mode_label(settings):
        return (getattr(settings, "download_mode", "") if settings else "") or "Not set"

    # ---- wiring ----

    pane_box = {}

    def right_rows(active, query):
        pane = pane_box.get("pane")
        if active == SETTINGS:
            if pane:
                pane.right_header = f"{Colors.BOLD}Settings{Colors.RESET}"
                pane.show_count = False
            return _settings_right()

        if pane:
            # The count would collide with the CHANGE column's right edge.
            pane.show_count = False
        if not active or active[0] != "drive":
            if pane:
                pane.right_header = ""
            return []

        folder_id = active[1]
        folder = folder_lookup.get(folder_id)
        if pane and folder:
            # Column labels live in the header band rather than as a first row,
            # so they stay put while a 79-setlist drive scrolls underneath.
            # One short of the pane width: the frame adds a single space itself.
            pane.right_header = _columns(
                f"{Colors.BOLD}{folder.get('name', '')}{Colors.RESET}",
                [("CHARTS", CHARTS_W, Colors.MUTED),
                 ("SIZE", SIZE_W, Colors.MUTED),
                 ("CHANGE", CHANGE_W, Colors.MUTED)],
                _right_text_width(),
            )
        return _drive_right(folder_id)

    def _refresh_folder(folder_id):
        """Repoint the left pane's numbers at the toggle that just happened.
        The fast path needs a stats cache to write through; without one the only
        correct option is to recompute the lot."""
        if folder_stats_cache is not None:
            update_menu_cache_on_toggle(
                cache, folder_id, folders, user_settings,
                folder_stats_cache, drives_config, background_scanner,
            )
        else:
            _copy_cache(cache, compute_main_menu_cache(
                folders, user_settings, download_path, drives_config,
                background_scanner=background_scanner,
            ))
        warmed.discard(folder_id)

    def on_right_enter(value):
        """Toggles stay on the screen; anything that needs another screen ends
        run() by returning a triple."""
        kind = value[0]
        if kind == "act":
            return (value[1], None)
        if kind == "setlist":
            _, folder_id, name = value
            if not user_settings.is_drive_enabled(folder_id):
                # A setlist inside a disabled drive: turn the drive on rather
                # than silently toggling something the user cannot see.
                user_settings.enable_drive(folder_id)
                if background_scanner:
                    folder = folder_lookup.get(folder_id)
                    for n in _setlists(folder) if folder else []:
                        background_scanner.notify_setlist_toggled(folder_id, n, True)
            else:
                state = user_settings.toggle_subfolder(folder_id, name)
                if background_scanner:
                    background_scanner.notify_setlist_toggled(folder_id, name, state)
            user_settings.save()
            _refresh_folder(folder_id)
            return None
        if kind in ("enable_all", "disable_all"):
            folder_id = value[1]
            folder = folder_lookup.get(folder_id)
            names = _setlists(folder) if folder else []
            if kind == "enable_all":
                if not user_settings.is_drive_enabled(folder_id):
                    user_settings.enable_drive(folder_id)
                user_settings.enable_all(folder_id, names)
            else:
                user_settings.disable_all(folder_id, names)
            if background_scanner:
                for n in names:
                    background_scanner.notify_setlist_toggled(folder_id, n, kind == "enable_all")
            user_settings.save()
            _refresh_folder(folder_id)
            return None
        if kind == "scan_folder":
            return ("scan_custom", value[1])
        if kind == "remove_folder":
            return ("remove_custom", value[1])
        return None

    def on_left_space(value):
        """Space toggles the whole drive. Enter is the other verb -- it focuses
        the right pane -- so the two must not share a callback."""
        if not value or value[0] != "drive":
            return None
        folder_id = value[1]
        user_settings.toggle_drive(folder_id)
        user_settings.save()
        _refresh_folder(folder_id)
        return None

    def footer():
        parts = [f"{Colors.PRIMARY}S{Colors.MUTED} {_sync_label(cache)}"]

        if background_scanner and not background_scanner.is_done():
            stats = background_scanner.get_stats()
            if stats.current_folder:
                verb = "Scanning" if stats.api_calls > 0 else "Loading cache"
                parts.append(f"{verb} {stats.current_folder} "
                             f"({stats.folders_done + 1}/{stats.folders_total})"
                             f" · {format_duration(stats.elapsed)}")
        # Nothing else goes here: the totals already sit in the title band, and
        # repeating them is how a status bar turns into noise.

        hints = (f"{Colors.PRIMARY}Tab{Colors.MUTED} panes  "
                 f"{Colors.PRIMARY}Space{Colors.MUTED} toggle  "
                 f"{Colors.PRIMARY}Esc{Colors.MUTED} quit")
        return (f"  {Colors.MUTED}{('   ·   '.join(parts))}{Colors.RESET}\n"
                f"  {hints}{Colors.RESET}")

    last_footer = {"text": None}

    def on_tick(_pane):
        if not background_scanner:
            return False
        changed = background_scanner.check_updates()
        if changed:
            if folder_stats_cache:
                folder_stats_cache.invalidate_all()
            _copy_cache(cache, compute_main_menu_cache(
                folders, user_settings, download_path, drives_config,
                folder_stats_cache, background_scanner,
            ))
            warmed.clear()
            last_footer["text"] = None
            return True

        # Otherwise repaint only when the one line that moves has actually
        # moved. Redrawing on every tick regardless is what made a running scan
        # look like it was flickering.
        text = footer()
        if text == last_footer["text"]:
            return False
        last_footer["text"] = text
        return True

    result_box = {}

    def key_sync():
        result_box["action"] = ("sync", None)
        return "return"

    pane = TwoPane(
        title="Chart Packs",
        subtitle=strip_ansi(cache.subtitle or ""),
        left_rows=left_rows,
        right_rows=right_rows,
        on_left_space=on_left_space,
        on_right_enter=on_right_enter,
        space_activates=True,
        left_header="Drives",
        left_width=LEFT_WIDTH,
        # The cursor row carries a background shift; an inverted chip on the
        # pane header as well was two things shouting the same thing.
        cursor_style="highlight",
        header_style="color",
        footer_lines=2,
        # The app owns its window, so the frame fills it and stays put rather
        # than resizing to whatever the current pane happens to hold.
        fill_height=True,
        left_enter_focuses_right=True,
        # No type-to-filter: the lists are short enough to look at, and it stole
        # Space and every letter from the rows underneath.
        right_filterable=False,
        footer=footer,
        keys={"s": key_sync, "S": key_sync},
        update_callback=on_tick if background_scanner else None,
        # The footer clock counts in seconds; polling far faster than it changes
        # only buys repaints nobody asked for.
        refresh_interval_ms=400,
    )
    pane_box["pane"] = pane
    pane._left_cursor = max(0, selected_index)

    # Put the cursor back where it was. The right-pane position only makes sense
    # if the left row still resolves to the same thing, so it is checked rather
    # than trusted -- a drive that vanished should not restore a stale cursor.
    rows = left_rows()
    pane._clamp_left(rows)
    if _LAST["left_value"] is not None and _LAST["left_value"] == pane._active_left_value(rows):
        pane.focus = _LAST["focus"]
        pane._cursor = _LAST["right_cursor"]
        pane._scroll = _LAST["right_scroll"]

    out = pane.run()
    position = pane._left_cursor

    rows = left_rows()
    pane._clamp_left(rows)
    _LAST.update(focus=pane.focus, right_cursor=pane._cursor,
                 right_scroll=pane._scroll,
                 left_value=pane._active_left_value(rows))

    if out is None:
        return ("quit", None, position)
    if isinstance(out, tuple):
        return (out[0], out[1], position)
    if out in ("s", "S"):
        action, value = result_box.get("action", ("sync", None))
        return (action, value, position)
    return ("quit", None, position)
