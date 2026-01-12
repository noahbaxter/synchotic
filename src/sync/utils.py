"""
Sync utility functions.
"""


def is_static_source(folder: dict) -> bool:
    """Check if folder is a static source (archive-based, not individual files)."""
    folder_id = folder.get("folder_id", "")
    return folder_id.startswith("collection:")


def get_sync_folder_name(folder: dict) -> str:
    """
    Get the folder name to use for sync_state paths and local folder creation.

    For static sources (with collection field), use collection as folder_name.
    This groups sources like "(2007) Rock Band 1" under "Rock Band/" and maintains
    backwards compatibility with old sync_state paths.

    For dynamic scan sources, use the source name directly.
    """
    # Static sources have collection - use it for grouping
    if folder.get("collection"):
        return folder["collection"]
    # Dynamic sources use their name
    return folder.get("name", "")
