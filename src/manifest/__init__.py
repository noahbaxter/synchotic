"""
Manifest management for DM Chart Sync.

Contains utilities for working with file lists (from scanner or legacy manifest).
"""

from .manifest import Manifest, FolderEntry, FileEntry
from .counter import (
    ChartType,
    ChartCounts,
    SubfolderStats,
    DriveStats,
    count_charts_in_files,
    is_sng_file,
    is_zip_file,
    has_folder_chart_markers,
    detect_chart_type_from_filenames,
)

__all__ = [
    # Core manifest types (for legacy/custom folder support)
    "Manifest",
    "FolderEntry",
    "FileEntry",
    # Chart counting
    "ChartType",
    "ChartCounts",
    "SubfolderStats",
    "DriveStats",
    "count_charts_in_files",
    "is_sng_file",
    "is_zip_file",
    "has_folder_chart_markers",
    "detect_chart_type_from_filenames",
]
