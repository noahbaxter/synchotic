#!/usr/bin/env python3
"""
Generate synthetic test fixtures for integration tests.

Creates small archive files with placeholder content that mimics the structure
of real chart files without requiring actual game data.

Usage:
    python scripts/generate_test_fixtures.py

Output:
    tests/integration/fixtures/test_archives/
        test_flat.zip           - Archive that extracts flat (files directly)
        test_nested.zip         - Archive with subdirectory structure
        test_flatten_match.zip  - Archive with single folder matching name (should flatten)
        test_unicode_ñame.zip   - Unicode in filenames
        test_special_chars.zip  - Colons, parentheses, etc.
        test_with_video.zip     - Includes a video file (for delete_videos test)
"""

import sys
import zipfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FIXTURES_DIR = PROJECT_ROOT / "tests" / "integration" / "fixtures" / "test_archives"


def create_song_ini(title: str = "Test Song", artist: str = "Test Artist") -> bytes:
    """Create a minimal song.ini file."""
    return f"""[Song]
name = {title}
artist = {artist}
charter = Synchotic Test
diff_drums = 5
preview_start_time = 0
""".encode("utf-8")


def create_notes_chart() -> bytes:
    """Create a minimal .chart file (placeholder)."""
    return b"""[Song]
{
  Resolution = 192
  Name = "Test"
}
[SyncTrack]
{
  0 = TS 4
  0 = B 120000
}
[Events]
{
}
[ExpertDrums]
{
  0 = N 0 0
}
"""


def create_notes_mid() -> bytes:
    """Create minimal MIDI header (placeholder - not playable)."""
    # Minimal MIDI header that's technically valid
    return bytes([
        0x4D, 0x54, 0x68, 0x64,  # MThd
        0x00, 0x00, 0x00, 0x06,  # Header length
        0x00, 0x01,              # Format type
        0x00, 0x01,              # Number of tracks
        0x01, 0xE0,              # Ticks per quarter note
        0x4D, 0x54, 0x72, 0x6B,  # MTrk
        0x00, 0x00, 0x00, 0x04,  # Track length
        0x00, 0xFF, 0x2F, 0x00,  # End of track
    ])


def create_audio_ogg() -> bytes:
    """Create minimal OGG header (placeholder - not playable)."""
    # Minimal OGG header - technically valid but no audio
    return bytes([
        0x4F, 0x67, 0x67, 0x53,  # OggS
        0x00, 0x02,              # Flags (BOS)
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  # Granule position
        0x00, 0x00, 0x00, 0x00,  # Serial number
        0x00, 0x00, 0x00, 0x00,  # Page sequence
        0x00, 0x00, 0x00, 0x00,  # Checksum
        0x01,                    # Page segments
        0x1E,                    # Segment table
    ]) + b"\x01vorbis" + b"\x00" * 20  # Vorbis header start


def create_album_png() -> bytes:
    """Create minimal PNG (1x1 transparent pixel)."""
    return bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D,  # IHDR length
        0x49, 0x48, 0x44, 0x52,  # IHDR
        0x00, 0x00, 0x00, 0x01,  # Width: 1
        0x00, 0x00, 0x00, 0x01,  # Height: 1
        0x08, 0x06,              # Bit depth, color type
        0x00, 0x00, 0x00,        # Compression, filter, interlace
        0x1F, 0x15, 0xC4, 0x89,  # CRC
        0x00, 0x00, 0x00, 0x0A,  # IDAT length
        0x49, 0x44, 0x41, 0x54,  # IDAT
        0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00, 0x05, 0x00, 0x01,  # Compressed data
        0x0D, 0x0A, 0x2D, 0xB4,  # CRC
        0x00, 0x00, 0x00, 0x00,  # IEND length
        0x49, 0x45, 0x4E, 0x44,  # IEND
        0xAE, 0x42, 0x60, 0x82,  # CRC
    ])


def create_video_mp4() -> bytes:
    """Create minimal MP4 header (for delete_videos test)."""
    # Minimal ftyp box - technically valid but no video content
    return b"\x00\x00\x00\x14ftypmp42\x00\x00\x00\x00mp42mp41"


def create_flat_archive(output_path: Path):
    """Archive with files directly at root (no subdirectory)."""
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("song.ini", create_song_ini("Flat Test", "Test Artist"))
        zf.writestr("notes.chart", create_notes_chart())
        zf.writestr("album.png", create_album_png())
    print(f"  Created: {output_path.name}")


def create_nested_archive(output_path: Path):
    """Archive with subdirectory structure."""
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Files in a subdirectory that doesn't match archive name
        zf.writestr("Chart Data/song.ini", create_song_ini("Nested Test"))
        zf.writestr("Chart Data/notes.mid", create_notes_mid())
        zf.writestr("Chart Data/song.ogg", create_audio_ogg())
        zf.writestr("Chart Data/album.png", create_album_png())
    print(f"  Created: {output_path.name}")


def create_flatten_match_archive(output_path: Path):
    """Archive with single folder matching archive name (should auto-flatten)."""
    # Archive is test_flatten_match.zip, folder inside is "test_flatten_match"
    stem = output_path.stem
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{stem}/song.ini", create_song_ini("Flatten Match Test"))
        zf.writestr(f"{stem}/notes.chart", create_notes_chart())
        zf.writestr(f"{stem}/song.ogg", create_audio_ogg())
    print(f"  Created: {output_path.name}")


def create_unicode_archive(output_path: Path):
    """Archive with unicode characters in filenames."""
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Señor Músico/song.ini", create_song_ini("Señor Músico", "日本語アーティスト"))
        zf.writestr("Señor Músico/notes.chart", create_notes_chart())
        zf.writestr("Señor Músico/album.png", create_album_png())
    print(f"  Created: {output_path.name}")


def create_special_chars_archive(output_path: Path):
    """Archive with special characters that need sanitization."""
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Colons get converted to " -" on Windows
        # Question marks get removed
        zf.writestr("Title - Subtitle/song.ini", create_song_ini("Title: Subtitle?", "Artist (2024)"))
        zf.writestr("Title - Subtitle/notes.chart", create_notes_chart())
    print(f"  Created: {output_path.name}")


def create_video_archive(output_path: Path):
    """Archive with a video file (for delete_videos test)."""
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("song.ini", create_song_ini("Video Test"))
        zf.writestr("notes.chart", create_notes_chart())
        zf.writestr("video.mp4", create_video_mp4())
        zf.writestr("album.png", create_album_png())
    print(f"  Created: {output_path.name}")


def create_empty_folders_archive(output_path: Path):
    """Archive with empty folders (edge case)."""
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("song.ini", create_song_ini("Empty Folder Test"))
        zf.writestr("notes.chart", create_notes_chart())
        # Create empty directory entry
        zf.writestr("EmptySubfolder/", "")
    print(f"  Created: {output_path.name}")


def create_deeply_nested_archive(output_path: Path):
    """Archive with deeply nested structure."""
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        deep_path = "Level1/Level2/Level3/Chart"
        zf.writestr(f"{deep_path}/song.ini", create_song_ini("Deep Nested"))
        zf.writestr(f"{deep_path}/notes.chart", create_notes_chart())
    print(f"  Created: {output_path.name}")


def main():
    print("Generating synthetic test fixtures...")
    print()

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    create_flat_archive(FIXTURES_DIR / "test_flat.zip")
    create_nested_archive(FIXTURES_DIR / "test_nested.zip")
    create_flatten_match_archive(FIXTURES_DIR / "test_flatten_match.zip")
    create_unicode_archive(FIXTURES_DIR / "test_unicode.zip")
    create_special_chars_archive(FIXTURES_DIR / "test_special_chars.zip")
    create_video_archive(FIXTURES_DIR / "test_with_video.zip")
    create_empty_folders_archive(FIXTURES_DIR / "test_empty_folders.zip")
    create_deeply_nested_archive(FIXTURES_DIR / "test_deeply_nested.zip")

    print()
    print(f"Generated {len(list(FIXTURES_DIR.glob('*.zip')))} test archives in:")
    print(f"  {FIXTURES_DIR}")

    # Print total size
    total = sum(f.stat().st_size for f in FIXTURES_DIR.glob("*.zip"))
    print(f"  Total size: {total / 1024:.1f} KB")


if __name__ == "__main__":
    main()
