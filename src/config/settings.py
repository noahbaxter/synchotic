"""
User settings management for DM Chart Sync.

Manages .dm-sync/settings.json - user preferences that persist across runs.
"""

import json
import re
from pathlib import Path

from . import jsonc


def normalize_setlist_name(name: str) -> str:
    """
    Normalize a setlist name for fuzzy matching.

    Handles common variations like:
    - "Guitar Hero III: Legends of Rock" vs "Guitar Hero III - Legends of Rock"
    - Different whitespace/punctuation around separators
    """
    # Replace common separator variations with a canonical form
    # ": " or " - " or " – " (en-dash) or " — " (em-dash) → single space
    normalized = re.sub(r'\s*[:\-–—]\s*', ' ', name)
    # Collapse multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized)
    # Lowercase for comparison
    return normalized.lower().strip()


# How blocked (virus-scan-flagged) files get downloaded. Empty means the user has
# not chosen yet and should be asked. Embedded OAuth is deliberately not offered:
# the 100-user cap is full, so it would fail for anyone new.
# Written by the OS, regenerated on sight, never part of a chart.
# ._* are macOS AppleDouble sidecars, which appear for every file on SMB and
# exFAT: exactly the volumes Library Path points people at.
DEFAULT_PURGE_IGNORE = ("._*", ".DS_Store", "Thumbs.db", "desktop.ini")

# Never fetched, and stripped out of archives as they are extracted. Videos are
# most of the size of a pack and Clone Hero does not need them to play a song.
DEFAULT_DOWNLOAD_IGNORE = ("*.mp4", "*.avi", "*.webm", "*.mkv", "*.mov")

DOWNLOAD_MODE_RCLONE = "rclone"
DOWNLOAD_MODE_ANONYMOUS = "anonymous"
DOWNLOAD_MODE_BYOC = "byoc"
DOWNLOAD_MODES = (DOWNLOAD_MODE_RCLONE, DOWNLOAD_MODE_ANONYMOUS, DOWNLOAD_MODE_BYOC)


SETTINGS_VERSION = 1


class _Field:
    """One entry in settings.json. Load, save and adoption all read this table,
    so their idea of a default cannot drift apart."""

    __slots__ = ("name", "_default", "coerce")

    def __init__(self, name, default, *, coerce=None):
        self.name = name
        self._default = default
        self.coerce = coerce

    def default(self):
        """A fresh default, so no two instances share a dict or list."""
        return self._default() if callable(self._default) else self._default

    def read(self, data):
        """The value in data, or the default when it is missing or junk (a
        coercer returns None for a value it cannot use)."""
        raw = data.get(self.name)
        value = self.coerce(raw) if self.coerce and raw is not None else raw
        return self.default() if value is None else value


def _as_mode(value):
    """An unknown mode reads as unchosen, so the app asks again."""
    return value if value in DOWNLOAD_MODES else ""


def _as_patterns(value):
    return list(value) if isinstance(value, list) else None


def _as_str(value):
    return str(value or "")


def _as_map(value):
    return value if isinstance(value, dict) else None


# Written in this order. People read this file, so the editable settings come
# first and the Drive ID maps last.
SETTING_FIELDS = (
    _Field("library_path", "", coerce=_as_str),
    _Field("download_mode", "", coerce=_as_mode),
    _Field("download_ignore", lambda: list(DEFAULT_DOWNLOAD_IGNORE),
           coerce=_as_patterns),
    _Field("purge_ignore", lambda: list(DEFAULT_PURGE_IGNORE), coerce=_as_patterns),
    _Field("drive_toggles", dict, coerce=_as_map),
    _Field("subfolder_toggles", dict, coerce=_as_map),
)

KNOWN_KEYS = frozenset(f.name for f in SETTING_FIELDS) | {"version"}

# Written by 1.5.4 and earlier, dropped on upgrade.
_RETIRED_KEYS = ("delete_videos", "group_expanded", "use_default_drives",
                 "oauth_prompted", "delta_mode")


def default_settings() -> dict:
    """settings.json as it stands before anyone has chosen anything."""
    return {f.name: f.default() for f in SETTING_FIELDS}


def chosen_settings(data) -> dict:
    """The entries that record a choice somebody made. A default is not a
    choice, and neither is a key we cannot interpret."""
    if not isinstance(data, dict):
        return {}
    chosen = {}
    for f in SETTING_FIELDS:
        if f.name not in data:
            continue
        value = data[f.name]
        if value not in ("", None, {}, []) and value != f.default():
            chosen[f.name] = value
    return chosen


TEMPLATE_FILENAME = "settings.template.jsonc"


def template_path() -> Path:
    """The template: in the bundle when frozen, in docs/ from source. Resolved
    from this file, not the app dir, which the launcher repoints."""
    import sys

    if getattr(sys, "frozen", False):
        from ..core.paths import get_bundle_dir
        return get_bundle_dir() / "docs" / TEMPLATE_FILENAME
    return Path(__file__).resolve().parents[2] / "docs" / TEMPLATE_FILENAME


def template_text() -> str:
    """The commented template, as shipped. Empty if it did not make the build."""
    try:
        return template_path().read_text()
    except OSError:
        return ""


def write_settings_file(path, data: dict) -> None:
    """Write settings.json with the template's comments around the values, or
    as plain JSON if the template did not make the build."""
    text = template_text()
    body = (jsonc.render(text, data) if text
            else json.dumps(data, indent=2) + "\n")
    Path(path).write_text(body)


def _keep_unreadable(path) -> None:
    """Move a settings file we could not parse aside, so the next save of
    defaults does not write over it."""
    from time import strftime

    try:
        Path(path).replace(Path(path).with_suffix(
            f".broken-{strftime('%Y%m%d-%H%M%S')}.json"))
    except OSError:
        pass


def unknown_settings(data) -> dict:
    """Entries we do not recognise, kept so a save does not drop them."""
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k not in KNOWN_KEYS}


class UserSettings:
    """
    Manages .dm-sync/settings.json - user preferences that persist across runs.

    Stores:
    - Drive toggle states (which drives are enabled/disabled at the top level)
    - Subfolder toggle states (which subfolders are enabled/disabled per drive)
    """

    # Fields are declared in SETTING_FIELDS and documented in
    # docs/settings.template.jsonc, which is the file the user edits.

    def __init__(self, path: Path):
        self.path = path
        for f in SETTING_FIELDS:
            setattr(self, f.name, f.default())
        # Which groups are open on the home screen. Not persisted.
        self.group_expanded: dict = {}
        # Keys from a hand edit or a newer version, carried through untouched.
        self._extra: dict = {}
        self._owed_drive_defaults = False

    @classmethod
    def load(cls, path: Path) -> "UserSettings":
        """Read settings.json, comments and trailing commas included."""
        settings = cls(path)

        if path.exists():
            try:
                data = jsonc.loads(path.read_text())
                if not isinstance(data, dict):
                    raise json.JSONDecodeError("not an object", "", 0)
                for f in SETTING_FIELDS:
                    setattr(settings, f.name, f.read(data))
                settings._extra = unknown_settings(data)
                settings._migrate(data)
            except (json.JSONDecodeError, OSError):
                _keep_unreadable(path)

        return settings

    def _migrate(self, data: dict) -> None:
        """Bring a file from before the settings had a version up to date."""
        if data.get("version") == SETTINGS_VERSION:
            return
        if "download_ignore" not in data and "delete_videos" in data:
            self.download_ignore = (list(DEFAULT_DOWNLOAD_IGNORE)
                                    if data.get("delete_videos") else [])
        # Files written by 1.5.4 and earlier had every unseen drive on unless
        # use_default_drives said the install was new, and the old loader
        # overruled that flag whenever the file showed any use. Carry the
        # corrected answer, written down as toggles by settle_drive_defaults.
        # Every such file carries a retired key; a hand-written one does not,
        # and must not wake up with every drive on.
        was_new = bool(data.get("use_default_drives", False)) and not (
            data.get("drive_toggles") or data.get("subfolder_toggles")
            or data.get("oauth_prompted"))
        written_by_old_version = any(k in data for k in _RETIRED_KEYS)
        self._owed_drive_defaults = written_by_old_version and not was_new
        for gone in _RETIRED_KEYS:
            self._extra.pop(gone, None)
        self.save()

    def settle_drive_defaults(self, drive_ids) -> bool:
        """Write down what an upgraded install already had on, once the drives
        are known. After this an undecided drive is off, as for a new install."""
        if not self._owed_drive_defaults:
            return False
        self._owed_drive_defaults = False
        added = False
        for drive_id in drive_ids:
            if drive_id not in self.drive_toggles:
                self.drive_toggles[drive_id] = True
                added = True
        if added:
            self.save()
        return added

    def reload(self):
        """Re-read the file into this object, in place. save() writes the whole
        object, so anything that edited settings.json underneath it (importing
        a previous install) would otherwise be erased by the next toggle."""
        fresh = UserSettings.load(self.path)
        for attr, value in vars(fresh).items():
            setattr(self, attr, value)

    def save(self):
        """Write the file back: values in table order, the template's comments
        around them, unrecognised keys after them."""
        data = {"version": SETTINGS_VERSION}
        data.update({f.name: getattr(self, f.name) for f in SETTING_FIELDS})
        data.update(self._extra)
        write_settings_file(self.path, data)

    @property
    def delete_videos(self) -> bool:
        """Whether videos are among the types we do not fetch. Derived from
        download_ignore, which the sync layer does not read yet."""
        return any(p in self.download_ignore for p in DEFAULT_DOWNLOAD_IGNORE)

    def is_drive_enabled(self, drive_id: str) -> bool:
        """Whether a drive is on. An undecided drive is off."""
        return self.drive_toggles.get(drive_id, False)

    def set_drive_enabled(self, drive_id: str, enabled: bool):
        """Set whether a drive is enabled at the top level."""
        self.drive_toggles[drive_id] = enabled

    def toggle_drive(self, drive_id: str) -> bool:
        """Toggle a drive's enabled state. Returns the new state."""
        current = self.is_drive_enabled(drive_id)
        self.set_drive_enabled(drive_id, not current)
        return not current

    def enable_drive(self, drive_id: str):
        """Enable a drive."""
        self.set_drive_enabled(drive_id, True)

    def is_subfolder_enabled(self, drive_id: str, subfolder_name: str) -> bool:
        """Check if a subfolder is enabled (defaults to True)."""
        return self.subfolder_toggles.get(drive_id, {}).get(subfolder_name, True)

    def set_subfolder_enabled(self, drive_id: str, subfolder_name: str, enabled: bool):
        """Set whether a subfolder is enabled."""
        if drive_id not in self.subfolder_toggles:
            self.subfolder_toggles[drive_id] = {}
        self.subfolder_toggles[drive_id][subfolder_name] = enabled

    def toggle_subfolder(self, drive_id: str, subfolder_name: str) -> bool:
        """Toggle a subfolder's enabled state. Returns the new state."""
        current = self.is_subfolder_enabled(drive_id, subfolder_name)
        self.set_subfolder_enabled(drive_id, subfolder_name, not current)
        return not current

    def get_disabled_subfolders(self, drive_id: str) -> set[str]:
        """Get set of disabled subfolder names for a drive."""
        toggles = self.subfolder_toggles.get(drive_id, {})
        return {name for name, enabled in toggles.items() if not enabled}

    def sync_subfolder_names(self, drive_id: str, discovered_names: list[str]) -> bool:
        """
        Sync stored subfolder settings with discovered names from Google Drive.

        Google Drive folder names are the source of truth. This method:
        1. Migrates settings from old names to new names (using normalized matching)
        2. Removes orphaned entries that no longer exist in Drive
        3. Preserves enabled/disabled state during migration

        Returns True if any changes were made.
        """
        if drive_id not in self.subfolder_toggles:
            return False

        old_toggles = self.subfolder_toggles[drive_id]
        new_toggles: dict[str, bool] = {}
        changed = False

        # Build normalized lookup for old settings
        # If multiple entries normalize to the same thing, prefer enabled=True
        # (user was probably trying to enable it when the duplicate was created)
        normalized_old: dict[str, tuple[str, bool]] = {}
        for old_name, enabled in old_toggles.items():
            norm = normalize_setlist_name(old_name)
            if norm in normalized_old:
                _, existing_enabled = normalized_old[norm]
                # Keep whichever is enabled (prefer True over False)
                if enabled or existing_enabled:
                    normalized_old[norm] = (old_name, enabled or existing_enabled)
            else:
                normalized_old[norm] = (old_name, enabled)

        # For each discovered name, find matching old setting
        for discovered_name in discovered_names:
            norm = normalize_setlist_name(discovered_name)

            if norm in normalized_old:
                old_name, enabled = normalized_old[norm]
                new_toggles[discovered_name] = enabled

                # Track if name changed
                if old_name != discovered_name:
                    changed = True
            # If no old setting exists, don't add one (default is enabled)

        # Check if we removed any orphaned entries
        if set(new_toggles.keys()) != set(old_toggles.keys()):
            changed = True

        if changed:
            self.subfolder_toggles[drive_id] = new_toggles

        return changed

    def enable_all(self, drive_id: str, subfolder_names: list[str]):
        """Enable all subfolders for a drive."""
        if drive_id not in self.subfolder_toggles:
            self.subfolder_toggles[drive_id] = {}
        for name in subfolder_names:
            self.subfolder_toggles[drive_id][name] = True

    def disable_all(self, drive_id: str, subfolder_names: list[str]):
        """Disable all subfolders for a drive."""
        if drive_id not in self.subfolder_toggles:
            self.subfolder_toggles[drive_id] = {}
        for name in subfolder_names:
            self.subfolder_toggles[drive_id][name] = False

    def is_group_expanded(self, group_name: str) -> bool:
        """Check if a group is expanded (all groups default to expanded)."""
        if group_name not in self.group_expanded:
            # Default: all groups expanded
            return True
        return self.group_expanded.get(group_name, True)

    def toggle_group_expanded(self, group_name: str) -> bool:
        """Toggle a group's expanded state. Returns the new state."""
        current = self.is_group_expanded(group_name)
        self.group_expanded[group_name] = not current
        return not current
