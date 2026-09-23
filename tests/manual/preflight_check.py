"""Run the pre-sync check against this machine's real library. Downloads nothing.

    ./venv/bin/python -m tests.manual.preflight_check
    ./venv/bin/python -m tests.manual.preflight_check --free 18G
    ./venv/bin/python -m tests.manual.preflight_check --free 18G --prompt

Reads the same settings, drives and stats cache the app reads, and prints what
sync would say before starting. --free pretends the library volume has that much
space left, which is how to see the prompt without filling a disk. --prompt shows
the confirmation itself rather than a summary.
"""
import argparse
import sys

from src.config import DrivesConfig, UserSettings
from src.core.formatting import format_size
from src.core.paths import (get_download_path, get_drives_config_path,
                            get_settings_path, set_library_path)
from src.sync.cache import get_persistent_stats_cache
from src.sync.preflight import concerns_for, gather
from src.ui.screens.preflight import confirm_sync


def _bytes(text: str) -> int:
    units = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
    text = text.strip().upper().rstrip("B")
    if text and text[-1] in units:
        return int(float(text[:-1]) * units[text[-1]])
    return int(text)


def _setlists(cache, folder_id):
    """Every setlist the cache has ever measured for this drive."""
    return sorted(cache._setlist_cache.get(folder_id, {}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--free", help="pretend this much space is left, e.g. 18G")
    parser.add_argument("--prompt", action="store_true",
                        help="show the confirmation instead of a summary")
    args = parser.parse_args()

    settings = UserSettings.load(get_settings_path())
    # get_library_path() reads module state, not settings, so the configured
    # library has to be applied first exactly as startup does it (sync.py). Skip
    # it and this reports on the default library while the app uses another one.
    set_library_path(settings.library_path or None)

    cache = get_persistent_stats_cache()
    library = get_download_path()

    drives = DrivesConfig.load(get_drives_config_path())
    folders = [
        {"folder_id": d.folder_id, "name": d.name,
         "setlists": _setlists(cache, d.folder_id)}
        for d in drives.drives
    ]

    usage = None
    if args.free:
        free = _bytes(args.free)

        class Fake:
            pass

        fake = Fake()
        fake.free = free
        usage = lambda path: fake  # noqa: E731

    needed, unmeasured, purge_charts, purge_bytes = gather(folders, settings, cache)
    concerns, free = concerns_for(folders, settings, cache, library, disk_usage=usage)

    if args.prompt:
        answer = confirm_sync(concerns, str(library), free)
        print(f"\n  sync would {'run' if answer else 'stop'}")
        return

    print(f"  library      {library}")
    print(f"  free         {format_size(free)}")
    print(f"  to download  {format_size(needed)}"
          f"{f' (plus {unmeasured} unmeasured drive(s))' if unmeasured else ''}")
    print(f"  to delete    {purge_charts} chart(s), {format_size(purge_bytes)}")
    print()
    if not concerns:
        print("  nothing to ask about; sync would start straight away")
        return
    for concern in concerns:
        print(f"  ! {concern.headline}")
        print(f"    {concern.detail}")


if __name__ == "__main__":
    sys.exit(main())
