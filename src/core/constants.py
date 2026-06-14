"""
Shared constants for DM Chart Sync.
"""

# Files that indicate a folder is a chart
CHART_MARKERS = {"song.ini", "notes.mid", "notes.chart"}

# OAuth client for user authentication (read-only scope)
# Desktop apps can't truly keep secrets - this is expected by Google
# Users authenticate with their own Google account to get their own download quota
USER_OAUTH_CLIENT_ID = "296168312762-8fvncs1v05glesaacd7posf6jo2ijsp1.apps.googleusercontent.com"
USER_OAUTH_CLIENT_SECRET = "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"
USER_OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Archive extensions that contain charts
CHART_ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar"}

# Video file extensions to delete from extracted charts
VIDEO_EXTENSIONS = {".mp4", ".avi", ".webm", ".mkv", ".mov"}


import platform as _platform

# Pinned rclone build. Bump deliberately: update version + SHA256s, test, release.
RCLONE_PINNED_VERSION = "1.69.1"
RCLONE_MIN_SYSTEM_VERSION = (1, 62, 0)  # system rclone must be >= this (backend copyid + rc)
RCLONE_REMOTE_NAME = "synchotic"

# SHA256 of each rclone-v<VERSION>-<os>-<arch>.zip from downloads.rclone.org/v<VERSION>/SHA256SUMS
# Verified against the official SHA256SUMS for v1.69.1 on 2026-06-13.
_RCLONE_BUILDS = {
    ("Windows", "AMD64"): ("rclone-v{v}-windows-amd64.zip", "0803f06d721e5399e48794538294099b195d51cc84b27bdb67e131096ad93ee4"),
    ("Darwin", "x86_64"): ("rclone-v{v}-osx-amd64.zip", "ebe1d5e13b0255605becfafbfa7c1809bc985272bcea0b342675c7e29c57629b"),
    ("Darwin", "arm64"): ("rclone-v{v}-osx-arm64.zip", "09b42295c30ba6b41a0d9c6741e4b5769de9ddecf5069f93c33f01bb46caa228"),
    ("Linux", "x86_64"): ("rclone-v{v}-linux-amd64.zip", "231841f8d8029ae6cfca932b601b3b50d0e2c3c2cb9da3166293f1c3eae7d79c"),
    ("Linux", "aarch64"): ("rclone-v{v}-linux-arm64.zip", "a03de8f700fcda7a1aef6b568f88d44218b698fb4e1637596c024d341bb24124"),
}


def rclone_download_info():
    """Return (url, sha256) for the current platform, or raise if unsupported."""
    key = (_platform.system(), _platform.machine())
    if key not in _RCLONE_BUILDS:
        raise RuntimeError(f"No pinned rclone build for {key}")
    fname_tmpl, sha = _RCLONE_BUILDS[key]
    fname = fname_tmpl.format(v=RCLONE_PINNED_VERSION)
    url = f"https://downloads.rclone.org/v{RCLONE_PINNED_VERSION}/{fname}"
    return url, sha
