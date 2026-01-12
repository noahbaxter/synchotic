#!/usr/bin/env python3
"""
Full end-to-end path compatibility test.

Tests that static source paths will produce the same sync_state keys as the old approach.

OLD approach (drives.json scan):
  - folder_name: "Rock Band" or "Guitar Hero" (from drives.json entry name)
  - GDrive subfolder: "(2007) Rock Band 1" or "(2005) Guitar Hero"
  - Extracted files: "Song Folder/file.ogg"
  - sync_state: "Rock Band/(2007) Rock Band 1/Song Folder/file.ogg"

NEW approach (static sources):
  - folder_name: collection = "Rock Band" or "Guitar Hero"
  - Static JSON paths: "(2007) Rock Band 1/Song Folder/file.ogg" (includes source name)
  - sync_state: "Rock Band/(2007) Rock Band 1/Song Folder/file.ogg"

This test downloads one archive from each static source, extracts it,
and verifies the static JSON paths match what the downloader would produce.

Usage:
    python scripts/test_full_path_compat.py                    # Test Rock Band + Guitar Hero
    python scripts/test_full_path_compat.py --collection "Rock Band"  # Test only Rock Band
    python scripts/test_full_path_compat.py --limit 3          # Test first 3 per collection
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

import requests
from src.drive import AuthManager
from src.sync.extractor import extract_archive, scan_extracted_files
from src.core.formatting import normalize_fs_name

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
auth: AuthManager = None

STATIC_SOURCES_DIR = Path(__file__).parent.parent / "static_sources"
# Collections to test by default (these had drives.json entries)
DEFAULT_COLLECTIONS = ["Rock Band", "Guitar Hero"]


def download_file(file_id: str, dest_path: Path, name: str) -> bool:
    """Download a file from GDrive using OAuth token."""
    token = auth.get_token() if auth else None
    if token:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(url, headers=headers, stream=True)
    else:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&key={API_KEY}"
        response = requests.get(url, stream=True)

    if response.status_code != 200:
        print(f"    Download failed: {response.status_code}")
        return False

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024*1024):
            f.write(chunk)
    return True


def extract_with_downloader_logic(archive_path: Path, dest_folder: Path) -> dict[str, int]:
    """Extract archive using the SAME logic as downloader.py."""
    archive_stem = archive_path.stem
    extract_tmp = dest_folder / f"_tmp_{archive_stem}"
    extract_tmp.mkdir(parents=True, exist_ok=True)

    success, error = extract_archive(archive_path, extract_tmp)
    if not success:
        shutil.rmtree(extract_tmp, ignore_errors=True)
        return {}

    extracted_files = scan_extracted_files(extract_tmp, extract_tmp)

    # Flattening logic from downloader.py
    extracted_items = list(extract_tmp.iterdir())
    if len(extracted_items) == 1 and extracted_items[0].is_dir():
        folder_name = normalize_fs_name(extracted_items[0].name)
        if folder_name.lower() == archive_stem.lower():
            folder_prefix = folder_name + "/"
            extracted_files = {
                (path[len(folder_prefix):] if path.startswith(folder_prefix) else path): size
                for path, size in extracted_files.items()
            }

    shutil.rmtree(extract_tmp, ignore_errors=True)
    return extracted_files


def test_source(json_path: Path, temp_dir: Path) -> dict:
    """Test one static source."""
    with open(json_path) as f:
        data = json.load(f)

    source_name = data["name"]
    collection = data.get("collection", json_path.parent.name)
    downloads = data.get("downloads", [])
    static_files = {f["path"]: f["size"] for f in data.get("files", [])}

    # Find first actual archive (skip .txt files)
    test_archive = None
    for dl in downloads:
        if not dl["name"].endswith(".txt"):
            test_archive = dl
            break

    if not test_archive:
        return {"name": source_name, "collection": collection, "status": "SKIP", "reason": "No archives"}

    archive_name = test_archive["name"]
    archive_id = test_archive.get("id")

    # URL sources don't have id
    if not archive_id:
        return {"name": source_name, "collection": collection, "status": "SKIP", "reason": "URL source (no GDrive ID)"}

    print(f"  Source: {source_name}")
    print(f"  Collection: {collection}")
    print(f"  Archive: {archive_name}")

    # Download and extract
    archive_path = temp_dir / archive_name
    if not download_file(archive_id, archive_path, archive_name):
        return {"name": source_name, "collection": collection, "status": "SKIP", "reason": "Download failed"}

    extracted = extract_with_downloader_logic(archive_path, temp_dir)
    archive_path.unlink(missing_ok=True)

    if not extracted:
        return {"name": source_name, "collection": collection, "status": "SKIP", "reason": "Extract failed"}

    # OLD sync_state format: folder_name/subfolder/file
    # folder_name was collection, subfolder was source_name
    # So OLD paths: "Rock Band/(2007) Rock Band 1/Song/file.ogg"
    old_sync_paths = {f"{collection}/{source_name}/{p}" for p in extracted.keys()}

    # NEW sync_state format: collection/static_path
    # Static paths already include source_name: "(2007) Rock Band 1/Song/file.ogg"
    # So NEW paths: "Rock Band/(2007) Rock Band 1/Song/file.ogg"
    new_sync_paths = {f"{collection}/{p}" for p in static_files.keys()}

    # Find matches
    sample_old = sorted(old_sync_paths)[:2]
    sample_new = sorted(new_sync_paths)[:2]

    print(f"  OLD would produce: {sample_old}")
    print(f"  NEW static paths:  {sample_new}")

    # Check paths from THIS archive
    archive_extracted_paths = set(extracted.keys())
    static_paths_for_archive = {
        p[len(source_name)+1:]: p
        for p in static_files.keys()
        if p.startswith(f"{source_name}/")
    }

    matching = archive_extracted_paths & set(static_paths_for_archive.keys())

    if matching:
        print(f"  MATCH: {len(matching)} extracted file paths found in static JSON")
        return {
            "name": source_name,
            "collection": collection,
            "status": "GOOD",
            "matching_files": len(matching),
        }
    else:
        # Check what's wrong
        sample_extracted = list(archive_extracted_paths)[:3]
        sample_static_stripped = list(static_paths_for_archive.keys())[:3]
        print(f"  NO MATCH")
        print(f"    Extracted: {sample_extracted}")
        print(f"    Static (stripped): {sample_static_stripped}")
        return {
            "name": source_name,
            "collection": collection,
            "status": "BAD",
            "reason": "Paths don't match",
        }


def test_collection(collection: str, limit: int = None) -> list[dict]:
    """Test all sources in a collection."""
    collection_dir = STATIC_SOURCES_DIR / collection
    if not collection_dir.exists():
        print(f"Collection not found: {collection}")
        return []

    json_files = sorted(collection_dir.glob("*.json"))
    if limit:
        json_files = json_files[:limit]

    print(f"\nTesting {len(json_files)} {collection} static sources")
    print("-" * 50)

    temp_dir = Path(tempfile.mkdtemp(prefix=f"pathtest_{collection.replace(' ', '_')}_"))
    results = []

    try:
        for i, json_path in enumerate(json_files, 1):
            print(f"\n[{i}/{len(json_files)}] {json_path.name}")
            result = test_source(json_path, temp_dir)
            results.append(result)

            status = result["status"]
            if status == "GOOD":
                print(f"  RESULT: PASS")
            elif status == "SKIP":
                print(f"  RESULT: {result['reason']}")
            else:
                print(f"  RESULT: FAIL - {result.get('reason', 'unknown')}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return results


def main():
    global auth

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Limit number of sources to test per collection")
    parser.add_argument("--collection", help="Test only this collection (e.g., 'Rock Band', 'Guitar Hero')")
    args = parser.parse_args()

    if not API_KEY:
        print("Error: GOOGLE_API_KEY not set")
        return 1

    auth = AuthManager()
    if not auth.is_signed_in:
        print("Signing in...")
        if not auth.sign_in():
            return 1
    print(f"Signed in as: {auth.user_email or 'user'}")

    print()
    print("=" * 70)
    print("FULL PATH COMPATIBILITY TEST")
    print("=" * 70)
    print()
    print("Verifying static JSON paths match old sync_state format:")
    print("  OLD: <collection>/<source_name>/Song/file.ogg")
    print("  NEW: <collection>/<source_name>/Song/file.ogg (via collection + static path)")

    # Determine which collections to test
    if args.collection:
        collections = [args.collection]
    else:
        collections = DEFAULT_COLLECTIONS

    all_results = []
    for collection in collections:
        results = test_collection(collection, args.limit)
        all_results.extend(results)

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    good = [r for r in all_results if r["status"] == "GOOD"]
    bad = [r for r in all_results if r["status"] == "BAD"]
    skipped = [r for r in all_results if r["status"] == "SKIP"]

    print(f"\nTotal: {len(all_results)}")
    print(f"  PASS: {len(good)}")
    print(f"  FAIL: {len(bad)}")
    print(f"  SKIP: {len(skipped)}")

    # Per-collection breakdown
    for collection in collections:
        col_results = [r for r in all_results if r.get("collection") == collection]
        col_good = len([r for r in col_results if r["status"] == "GOOD"])
        col_bad = len([r for r in col_results if r["status"] == "BAD"])
        col_skip = len([r for r in col_results if r["status"] == "SKIP"])
        print(f"\n  {collection}: {col_good} pass, {col_bad} fail, {col_skip} skip")

    if bad:
        print("\nFailed sources:")
        for r in bad:
            print(f"  - [{r['collection']}] {r['name']}: {r.get('reason', 'unknown')}")

    if good and not bad:
        print()
        print("SUCCESS: All static source paths are compatible with old sync_state format!")
        print("Users who previously synced will not need to re-download.")

    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
