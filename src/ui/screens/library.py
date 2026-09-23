"""Point Synchotic at a different chart library.

The library is self-contained: markers and staging live inside it, so moving
the folder moves its state with it. Changing this setting migrates nothing, it
just looks somewhere else, which is why the screen says what it found there.
"""

from pathlib import Path

from ... import copy
from ..widgets import display
from ..widgets.confirm import ConfirmDialog


LIBRARY_STEP = copy.STEP_LIBRARY


def ask(title: str, body: str, options, setup_step=None, esc_label=copy.BTN_CANCEL,
        step_name=""):
    """One boxed question, drawn the same way by every setup step.

    A menu because it waits for an answer and repaints, so the body travels
    as its subtitle to stay on screen. `options` is [(label, value), ...].
    Returns the chosen value, or None.
    """
    from ..widgets.menu import Menu, MenuItem

    heading, subtitle = display.setup_frame(title, body, setup_step, step_name)

    menu = Menu(title=heading, subtitle=subtitle, esc_label=esc_label)
    for label, value in options:
        menu.add_item(MenuItem(label=label, value=value))
    result = menu.run()
    return result.value if result else None


def _known_drive_names() -> list:
    """Every drive Synchotic can sync, from the shipped manifest rather than
    what is enabled: a folder named after a drive switched off is still
    evidence a previous install wrote it."""
    try:
        from ...config import DrivesConfig
        from ...core.paths import get_drives_config_path
        return [d.name for d in DrivesConfig.load(get_drives_config_path()).drives]
    except Exception:
        return []


def _ask_for_path(intro: str, can_browse: bool, setup_step) -> str:
    """One list: pick a folder or type one. Returns the path, or "" for backed
    out. Cancelling the native dialog reopens this screen instead."""
    from ..widgets.menu import Menu, MenuItem
    from ...core.folder_picker import pick_folder
    from ...core.paths import get_library_path, plain_path

    current = plain_path(get_library_path())
    heading, subtitle = display.setup_frame(copy.LIBRARY_QUESTION, intro,
                                            setup_step, LIBRARY_STEP)
    typed = ""
    while True:
        menu = Menu(title=heading, subtitle=subtitle, esc_label=copy.BTN_CANCEL)
        if can_browse:
            menu.add_item(MenuItem(label=copy.LIBRARY_BROWSE, value="browse"))
        # Whatever was typed before the dialog was opened survives it.
        menu.add_item(MenuItem(label=copy.LIBRARY_TYPE, value="type",
                               editable=True, text=typed, placeholder=current))

        result = menu.run()
        if result is None:
            return ""
        if result.item.value != "browse":
            return _clean(result.item.text)

        picked = pick_folder(copy.LIBRARY_QUESTION, current)
        if picked:
            return _clean(picked)
        typed = menu.items[-1].text


def _clean(entered) -> str:
    # A path dragged into a terminal arrives wrapped in quotes.
    return str(entered).strip().strip('"').strip("'").strip()


def _drive_contents(path) -> tuple:
    """(group, drive name, setlists on disk) per drive folder in `path`, in
    manifest order, the order the home screen lists them in."""
    try:
        from ...config import DrivesConfig
        from ...core.paths import (LIBRARY_STATE_DIR_NAME,
                                   get_drives_config_path)
        from ...sync.library_probe import previous_selection

        drives = DrivesConfig.load(get_drives_config_path()).drives
        found = previous_selection(path, drives,
                                   skip=(LIBRARY_STATE_DIR_NAME,))
        return tuple((d.group, d.name, len(found[d.folder_id]))
                     for d in drives if d.folder_id in found)
    except Exception:
        return ()


def show_library_screen(user_settings, intro: str = "", setup_step=None) -> bool:
    """Prompt for a new library path. Returns True when it changed.

    `intro` is said above the prompt. It is passed in rather than printed
    first: this screen redraws, so a caller that prints ahead of it loses it.
    """
    from ...core.paths import (LIBRARY_STATE_DIR_NAME, plain_path,
                               set_library_path)
    from ...core.folder_picker import picker_available
    from ...sync.library_probe import Look, probe_library
    from ..primitives import working

    # With no picker at all (headless, SSH) typing is the only row.
    can_browse = picker_available()

    # A rejected folder goes back to the picker, not out of the screen.
    while True:
        picked = _ask_for_path(intro, can_browse, setup_step)
        if not picked:
            return False
        path = Path(picked).expanduser()

        if path.exists() and not path.is_dir():
            display.library_not_a_folder(path)
            continue

        if not path.exists():
            if not ConfirmDialog(copy.FOLDER_CREATE_ASK.format(path=path)).run():
                continue
            try:
                path.mkdir(parents=True)
            except OSError as e:
                display.library_create_failed(e)
                continue

        # Only the folder's own state dir counts as ours.
        ours = (path / LIBRARY_STATE_DIR_NAME / "markers").exists()

        seen = {"charts": 0, "files": 0}

        def progress(charts, files):
            seen["charts"], seen["files"] = charts, files

        def label():
            reading = copy.LIBRARY_READING.format(path=plain_path(path))
            if not seen["files"]:
                return reading
            return f"{reading}  " + copy.LIBRARY_READ_SO_FAR.format(
                charts=f"{seen['charts']:,}", files=f"{seen['files']:,}")

        # A library we already sync is not walked: its drive listing below
        # says what is there, and walking an external drive to learn the same
        # thing worse took seconds.
        if ours:
            look = Look()
        else:
            look = working(label,
                           lambda: probe_library(path, _known_drive_names(),
                                                 skip=(LIBRARY_STATE_DIR_NAME,),
                                                 on_progress=progress))

        contents = ()
        if ours or look.drive_matches:
            contents = _drive_contents(path)

        question, body, risky = display.library_summary(
            plain_path(path), chart_folders=look.chart_folders, files=look.files,
            folders=look.folders, more=look.capped,
            drive_matches=look.drive_matches, has_markers=ours,
            contents=contents)

        # When charts are at stake the cursor starts on No, so a reflexive
        # Enter cannot delete a collection.
        options = [(copy.LIBRARY_USE, True), (copy.LIBRARY_PICK_ANOTHER, False)]
        if risky:
            options.reverse()

        if not ask(question, body, options, setup_step=setup_step,
                   esc_label=copy.BTN_BACK, step_name=LIBRARY_STEP):
            continue

        break

    user_settings.library_path = str(path)
    user_settings.save()

    # Apply now, not at next launch: every path helper reads module state, so
    # leaving it stale would keep writing into the old library this session.
    set_library_path(path)
    from ...sync.cache import clear_cache, get_persistent_stats_cache
    clear_cache()
    # Every stat here was measured against the old library, and nothing
    # recomputes a setlist that is already cached. The Drive scan cache stays:
    # it describes Drive, not disk.
    stats = get_persistent_stats_cache()
    stats.invalidate_all()
    stats.save()
    return True
