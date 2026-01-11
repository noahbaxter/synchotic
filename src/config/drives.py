"""
Source configuration management for DM Chart Sync.

Manages sources.json - the hierarchical list of all chart sources.

Source types:
  - url: CDN direct download
  - file: Google Drive single file
  - folder: Google Drive folder (static, pre-scanned)
  - scan: Google Drive folder (dynamic, live-scanned)
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Literal


SourceType = Literal["url", "file", "folder", "scan"]


@dataclass
class DriveConfig:
    """A source configuration."""
    name: str
    source_type: SourceType  # url, file, folder, or scan
    link: str  # URL or GDrive ID
    description: str = ""
    group: str = ""  # Top-level grouping (Games, Drums, etc.)
    collection: str = ""  # Mid-level grouping (Guitar Hero, BirdmanExe, etc.)
    hidden: bool = False  # If True, hide from sync UI
    rescan_hours: int = 6  # For scan type: how often to force rescan

    @property
    def is_dynamic(self) -> bool:
        """Returns True if this source needs live scanning."""
        return self.source_type == "scan"

    @property
    def folder_id(self) -> str:
        """Get folder ID for folder/scan types. For backward compatibility."""
        if self.source_type in ("folder", "scan"):
            return self.link
        return ""

    @property
    def file_id(self) -> str:
        """Get file ID for file type. For backward compatibility."""
        if self.source_type == "file":
            return self.link
        return ""

    @property
    def url(self) -> str:
        """Get URL for url type. For backward compatibility."""
        if self.source_type == "url":
            return self.link
        return ""

    def to_dict(self) -> dict:
        """Convert to dict for manifest_gen.py ROOT_FOLDERS format."""
        d = {
            "name": self.name,
            "folder_id": self.link if self.source_type in ("folder", "scan") else "",
            "description": self.description,
        }
        if self.group:
            d["group"] = self.group
        if self.collection:
            d["collection"] = self.collection
        if self.hidden:
            d["hidden"] = self.hidden
        if self.is_dynamic and self.rescan_hours != 6:
            d["rescan_hours"] = self.rescan_hours
        return d

    @classmethod
    def from_dict(cls, data: dict, group: str = "", collection: str = "") -> "DriveConfig":
        """Create from dict. Supports old and new formats."""
        # New format: type + link
        if "type" in data:
            return cls(
                name=data.get("name", ""),
                source_type=data["type"],
                link=data.get("link", ""),
                description=data.get("description", ""),
                group=group or data.get("group", ""),
                collection=collection,
                hidden=data.get("hidden", False),
                rescan_hours=data.get("rescan_hours", 6),
            )

        # Old format: file/folder/url + dynamic flag
        if data.get("url"):
            source_type = "url"
            link = data["url"]
        elif data.get("file"):
            source_type = "file"
            link = data["file"]
        elif data.get("dynamic"):
            source_type = "scan"
            link = data.get("folder", "") or data.get("folder_id", "")
        else:
            source_type = "folder"
            link = data.get("folder", "") or data.get("folder_id", "")

        return cls(
            name=data.get("name", ""),
            source_type=source_type,
            link=link,
            description=data.get("description", ""),
            group=group or data.get("group", ""),
            collection=collection,
            hidden=data.get("hidden", False),
            rescan_hours=data.get("rescan_hours", 6),
        )


class DrivesConfig:
    """
    Manages sources.json - the hierarchical list of all chart sources.

    Format:
    {
        "GROUP": {
            "COLLECTION": [
                {"name": "...", "type": "url", "link": "https://..."},
                {"name": "...", "type": "file", "link": "GDRIVE_ID"},
                {"name": "...", "type": "folder", "link": "GDRIVE_ID"},
                {"name": "...", "type": "scan", "link": "GDRIVE_ID"}
            ]
        }
    }
    """

    def __init__(self, path: Path):
        self.path = path
        self.drives: list[DriveConfig] = []

    @classmethod
    def load(cls, path: Path) -> "DrivesConfig":
        """Load sources configuration from file."""
        config = cls(path)

        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)

                # Check for old format (drives.json)
                if "drives" in data:
                    for drive_data in data["drives"]:
                        # Old format: all drives are dynamic (for scanning)
                        drive_data["dynamic"] = True
                        config.drives.append(DriveConfig.from_dict(drive_data))
                else:
                    # New hierarchical format (sources.json)
                    for group_name, collections in data.items():
                        for collection_name, sources in collections.items():
                            for source_data in sources:
                                config.drives.append(DriveConfig.from_dict(
                                    source_data,
                                    group=group_name,
                                    collection=collection_name
                                ))
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load sources: {e}")

        return config

    def save(self):
        """Save sources configuration to file (hierarchical format)."""
        data = {}
        for drive in self.drives:
            group = drive.group or "Other"
            collection = drive.collection or "Uncategorized"
            if group not in data:
                data[group] = {}
            if collection not in data[group]:
                data[group][collection] = []

            # Build source entry with new format
            entry = {
                "name": drive.name,
                "type": drive.source_type,
                "link": drive.link,
            }
            if drive.description:
                entry["description"] = drive.description

            data[group][collection].append(entry)

        with open(self.path, "w") as f:
            json.dump(data, f, indent=2)

    def get_drive(self, source_id: str) -> Optional[DriveConfig]:
        """Get drive by folder ID, file ID, or URL."""
        for drive in self.drives:
            if drive.folder_id == source_id or drive.file_id == source_id or drive.url == source_id:
                return drive
        return None

    def get_drive_by_name(self, name: str) -> Optional[DriveConfig]:
        """Get drive by name."""
        for drive in self.drives:
            if drive.name == name:
                return drive
        return None

    def to_root_folders_list(self) -> list[dict]:
        """Convert dynamic drives to ROOT_FOLDERS format for manifest_gen.py."""
        return [d.to_dict() for d in self.drives if d.is_dynamic]

    def get_visible_drives(self) -> list[DriveConfig]:
        """Get drives that are not hidden."""
        return [d for d in self.drives if not d.hidden]

    def get_dynamic_drives(self) -> list[DriveConfig]:
        """Get drives that need live scanning (type=scan)."""
        return [d for d in self.drives if d.is_dynamic]

    def get_static_sources(self) -> list[DriveConfig]:
        """Get sources that use pre-generated manifests (type=url/file/folder)."""
        return [d for d in self.drives if not d.is_dynamic]

    def get_groups(self, visible_only: bool = True) -> list[str]:
        """Get unique group names in order of first appearance."""
        seen = set()
        groups = []
        drives = self.get_visible_drives() if visible_only else self.drives
        for drive in drives:
            if drive.group and drive.group not in seen:
                seen.add(drive.group)
                groups.append(drive.group)
        return groups

    def get_collections_in_group(self, group: str, visible_only: bool = True) -> list[str]:
        """Get unique collection names within a group."""
        seen = set()
        collections = []
        drives = self.get_visible_drives() if visible_only else self.drives
        for drive in drives:
            if drive.group == group and drive.collection and drive.collection not in seen:
                seen.add(drive.collection)
                collections.append(drive.collection)
        return collections

    def get_drives_in_group(self, group: str, visible_only: bool = True) -> list[DriveConfig]:
        """Get all drives in a specific group."""
        drives = self.get_visible_drives() if visible_only else self.drives
        return [d for d in drives if d.group == group]

    def get_drives_in_collection(self, group: str, collection: str, visible_only: bool = True) -> list[DriveConfig]:
        """Get all drives in a specific collection."""
        drives = self.get_visible_drives() if visible_only else self.drives
        return [d for d in drives if d.group == group and d.collection == collection]

    def get_ungrouped_drives(self, visible_only: bool = True) -> list[DriveConfig]:
        """Get drives that don't belong to any group."""
        drives = self.get_visible_drives() if visible_only else self.drives
        return [d for d in drives if not d.group]
