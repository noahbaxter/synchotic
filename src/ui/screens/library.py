"""Point Synchotic at a different chart library.

The library is self-contained: markers and staging live inside it, so moving
the folder moves its state with it. Changing this setting therefore does not
migrate anything, it just looks somewhere else. A folder Synchotic has never
synced reads as empty and the next sync re-downloads into it, which is worth
saying out loud before the user finds out by watching it happen.
"""

from pathlib import Path

from ..primitives import clear_screen
from ..components import print_header
from ..widgets import display
from ..widgets.confirm import ConfirmDialog


def show_library_screen(user_settings) -> bool:
    """Prompt for a new library path. Returns True when it changed."""
    from ...core.paths import (LIBRARY_STATE_DIR_NAME, find_legacy_markers,
                               get_library_path, migrate_to_os_dirs,
                               find_legacy_install, set_library_path)
    from ..primitives import CancelInput, input_with_esc

    clear_screen()
    print_header()
    display.library_prompt(get_library_path())

    try:
        entered = input_with_esc("  New path: ")
    except CancelInput:
        return False
    if not entered.strip():
        return False

    path = Path(entered.strip().strip('"').strip("'")).expanduser()

    if path.exists() and not path.is_dir():
        display.library_not_a_folder(path)
        return False

    if not path.exists():
        if not ConfirmDialog(f"Create {path}?").run():
            return False
        try:
            path.mkdir(parents=True)
        except OSError as e:
            display.library_create_failed(path, e)
            return False

    # No markers means Synchotic has never synced here, so every chart it
    # already has elsewhere will be fetched again into this folder. Pre-1.5
    # installs kept markers in .dm-sync beside the launcher, so check there too
    # before telling anyone their library is new.
    if not (path / LIBRARY_STATE_DIR_NAME / "markers").exists() and not find_legacy_markers(path):
        display.library_is_new(path)
        if not ConfirmDialog("Use this folder anyway?").run():
            return False

    user_settings.library_path = str(path)
    user_settings.save()

    # Apply now, not at next launch: every path helper reads module state, so
    # leaving it stale would keep writing into the old library for this session.
    set_library_path(path)
    from ...sync.cache import clear_cache
    clear_cache()

    # Adopt a pre-1.5 install now that we know where it is. Runs after
    # clear_cache so the scan cache it brings over survives, and it copies
    # rather than moves, so the old folder still works if this goes wrong.
    legacy = find_legacy_install(path)
    if legacy is not None:
        moved = migrate_to_os_dirs(legacy)
        if moved:
            display.library_imported(legacy, moved)

    display.library_changed(path)
    return True
