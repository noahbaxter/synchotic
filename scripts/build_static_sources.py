#!/usr/bin/env python3
"""
Generate static source JSONs from sources.json.

Reads sources.json and generates individual static source files for each
non-scan entry (file, folder, url types). These contain:
- downloads: archive files to download (with md5/size for verification)
- files: extracted content (path/size for post-extraction validation)

Usage:
    # Generate all missing static sources
    python scripts/build_static_sources.py

    # Force regenerate specific source
    python scripts/build_static_sources.py --name "Anti Hero" --force

    # Dry run to see what would be generated
    python scripts/build_static_sources.py --dry-run
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env file if it exists
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

import requests

from src.drive import DriveClient, DriveClientConfig, FolderScanner, AuthManager
from src.manifest import count_charts_in_files
from src.sync.extractor import extract_archive, scan_extracted_files
from src.core.constants import CHART_ARCHIVE_EXTENSIONS

API_KEY = os.environ.get("GOOGLE_API_KEY", "")
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for faster downloads

# Reusable session for connection pooling
http_session = requests.Session()
SOURCES_FILE = Path(__file__).parent.parent / "sources.json"
STATIC_DIR = Path(__file__).parent.parent / "static_sources"

# Global auth manager (initialized in main)
auth: AuthManager = None


def get_output_path(collection: str, name: str) -> Path:
    return STATIC_DIR / collection / f"{name}.json"


def is_archive(filename: str) -> bool:
    return any(filename.lower().endswith(ext) for ext in CHART_ARCHIVE_EXTENSIONS)


def download_gdrive_file(client: DriveClient, file_id: str, dest_path: Path) -> dict:
    """Download a GDrive file. Returns metadata dict."""
    metadata = client.get_file_metadata(
        file_id,
        fields="id,name,size,md5Checksum,mimeType"
    )
    if not metadata:
        raise Exception(f"Could not get metadata for {file_id}")

    name = metadata.get("name", "file")
    size = int(metadata.get("size", 0))

    print(f"    Downloading {name} ({size / 1024 / 1024:.1f} MB)...")

    # Use OAuth token for download (API key doesn't work for restricted files)
    token = auth.get_token() if auth else None
    if token:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        headers = {"Authorization": f"Bearer {token}"}
        response = http_session.get(url, headers=headers, stream=True)
    else:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&key={client.config.api_key}"
        response = http_session.get(url, stream=True)
    response.raise_for_status()

    downloaded = 0
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            f.write(chunk)
            downloaded += len(chunk)
            if size > 0:
                pct = downloaded * 100 // size
                print(f"\r    {downloaded / 1024 / 1024:.1f} / {size / 1024 / 1024:.1f} MB ({pct}%)", end="", flush=True)
    print()

    return {
        "id": file_id,
        "name": name,
        "size": size,
        "md5": metadata.get("md5Checksum", ""),
    }


def download_gdrive_file_quiet(file_id: str, dest_path: Path, name: str, size: int, md5: str) -> dict:
    """Download a GDrive file without progress output (for parallel downloads).

    Takes all metadata as params to avoid extra API calls - folder scan already has this info.
    """
    # Use OAuth token for download
    token = auth.get_token() if auth else None
    if token:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        headers = {"Authorization": f"Bearer {token}"}
        response = http_session.get(url, headers=headers, stream=True)
    else:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&key={API_KEY}"
        response = http_session.get(url, stream=True)
    response.raise_for_status()

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            f.write(chunk)

    return {"id": file_id, "name": name, "size": size, "md5": md5}


def download_url(url: str, dest_path: Path) -> dict:
    """Download from URL. Returns metadata dict with computed md5."""
    name = url.split("/")[-1].split("?")[0]
    # URL decode the name
    from urllib.parse import unquote
    name = unquote(name)

    print(f"    Downloading {name}...")

    response = http_session.get(url, stream=True)
    response.raise_for_status()

    size = int(response.headers.get("content-length", 0))
    downloaded = 0
    md5_hash = hashlib.md5()

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            f.write(chunk)
            md5_hash.update(chunk)
            downloaded += len(chunk)
            if size > 0:
                pct = downloaded * 100 // size
                print(f"\r    {downloaded / 1024 / 1024:.1f} / {size / 1024 / 1024:.1f} MB ({pct}%)", end="", flush=True)
    print()

    actual_size = dest_path.stat().st_size

    return {
        "url": url,
        "name": name,
        "size": actual_size,
        "md5": md5_hash.hexdigest(),
    }


def list_gdrive_folder(client: DriveClient, folder_id: str) -> list[dict]:
    """List files in a GDrive folder."""
    scanner = FolderScanner(client)
    result = scanner.scan(folder_id)

    files = []
    for f in result.files:
        files.append({
            "id": f["id"],
            "name": f["name"],
            "size": int(f.get("size", 0)),
            "md5": f.get("md5", ""),
            "path": f.get("path", f["name"]),
        })

    return files


def extract_and_scan(archive_path: Path, extract_dir: Path) -> dict[str, int]:
    """Extract archive and return {path: size} dict."""
    success, error = extract_archive(archive_path, extract_dir)
    if not success:
        raise Exception(f"Extract failed: {error}")
    return scan_extracted_files(extract_dir, extract_dir)


def process_source(
    source_type: str,
    link: str,
    name: str,
    group: str,
    collection: str,
    release_date: str = None,
    client: DriveClient = None,
    temp_dir: Path = None,
) -> dict:
    """Process a single source entry. Returns the static source dict."""
    downloads = []
    all_extracted = {}

    if source_type == "file":
        # Single GDrive file
        dl_path = temp_dir / "download"
        meta = download_gdrive_file(client, link, dl_path)
        actual_path = temp_dir / meta["name"]
        dl_path.rename(actual_path)
        downloads.append(meta)

        if is_archive(meta["name"]):
            print(f"    Extracting {meta['name']}...")
            extract_dir = temp_dir / "extracted"
            extract_dir.mkdir()
            all_extracted = extract_and_scan(actual_path, extract_dir)
        else:
            all_extracted[meta["name"]] = meta["size"]

    elif source_type == "folder":
        # GDrive folder with multiple files - download in parallel
        print(f"    Scanning folder...")
        folder_files = list_gdrive_folder(client, link)
        if not folder_files:
            raise Exception("Folder scan returned 0 files (may be private or inaccessible)")
        print(f"    Found {len(folder_files)} files")

        extract_dir = temp_dir / "extracted"
        extract_dir.mkdir()

        # Download all files in parallel
        print_lock = Lock()
        completed = [0]

        def download_one(idx, f):
            dl_path = temp_dir / f"dl_{idx}"
            meta = download_gdrive_file_quiet(f["id"], dl_path, f["name"], f["size"], f["md5"])
            with print_lock:
                completed[0] += 1
                print(f"    [{completed[0]}/{len(folder_files)}] {f['name']} ({meta['size'] / 1024 / 1024:.1f} MB)")
            return idx, f, meta, dl_path

        max_workers = 24
        print(f"    Downloading {len(folder_files)} files ({max_workers} parallel)...")
        download_results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(download_one, i, f): i for i, f in enumerate(folder_files, 1)}
            for future in as_completed(futures):
                download_results.append(future.result())

        # Process downloads (extract archives sequentially to avoid file handle limits)
        archive_count = sum(1 for _, f, _, _ in download_results if is_archive(f["name"]))
        extracted_count = [0]
        print(f"    Extracting {archive_count} archives...")
        for idx, f, meta, dl_path in sorted(download_results, key=lambda x: x[0]):
            downloads.append({
                "id": f["id"],
                "name": f["name"],
                "size": meta["size"],
                "md5": meta["md5"],
                "path": f["path"],
            })

            if is_archive(f["name"]):
                extracted_count[0] += 1
                print(f"    [{extracted_count[0]}/{archive_count}] {f['name']}", end="", flush=True)

                archive_stem = Path(f["name"]).stem
                sub_extract = extract_dir / archive_stem
                sub_extract.mkdir(exist_ok=True)

                actual_path = temp_dir / f["name"]
                dl_path.rename(actual_path)

                extracted = extract_and_scan(actual_path, sub_extract)
                for path, size in extracted.items():
                    # Don't add archive_stem prefix - matches old downloader behavior
                    all_extracted[path] = size

                print(f" -> {len(extracted)} files")
                actual_path.unlink()
            else:
                dest = extract_dir / f["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dl_path.rename(dest)
                all_extracted[f["path"]] = f["size"]

    elif source_type == "url":
        # CDN URL
        dl_path = temp_dir / "download"
        meta = download_url(link, dl_path)
        actual_path = temp_dir / meta["name"]
        dl_path.rename(actual_path)
        downloads.append(meta)

        if is_archive(meta["name"]):
            print(f"    Extracting {meta['name']}...")
            extract_dir = temp_dir / "extracted"
            extract_dir.mkdir()
            all_extracted = extract_and_scan(actual_path, extract_dir)
        else:
            all_extracted[meta["name"]] = meta["size"]

    else:
        raise ValueError(f"Unknown source type: {source_type}")

    # Build output - prefix paths with source name for old sync_state compatibility
    # Old approach: Rock Band/(2007) Rock Band 1/Song/file.ogg
    # New approach needs: source name in path so collection + path matches old structure
    files_list = [{"path": f"{name}/{p}", "size": s} for p, s in sorted(all_extracted.items())]
    stats = count_charts_in_files(files_list)

    name_slug = name.lower().replace(" ", "-").replace("(", "").replace(")", "").replace(":", "")
    folder_id = f"static-{name_slug}"

    result = {
        "name": name,
        "folder_id": folder_id,
        "group": group,
        "collection": collection,
        "downloads": downloads,
        "download_size": sum(d["size"] for d in downloads),
        "files": files_list,
        "extracted_size": sum(all_extracted.values()),
        "file_count": len(files_list),
        "chart_count": stats.chart_counts.total,
    }
    if release_date:
        result["release_date"] = release_date
    return result


def cleanup_old_temp_dirs():
    """Remove old static_* temp directories from previous runs."""
    import glob
    temp_base = tempfile.gettempdir()
    old_dirs = glob.glob(os.path.join(temp_base, "static_*"))
    if old_dirs:
        print(f"Cleaning up {len(old_dirs)} old temp directories...")
        for d in old_dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass


def load_sources() -> list[dict]:
    """Load sources.json and flatten into list of source entries."""
    with open(SOURCES_FILE) as f:
        data = json.load(f)

    sources = []
    for group, collections in data.items():
        for collection, entries in collections.items():
            for entry in entries:
                source = {
                    "name": entry["name"],
                    "type": entry["type"],
                    "link": entry["link"],
                    "group": group,
                    "collection": collection,
                }
                if "release_date" in entry:
                    source["release_date"] = entry["release_date"]
                sources.append(source)
    return sources


def main():
    parser = argparse.ArgumentParser(description="Generate static source JSONs from sources.json")
    parser.add_argument("--name", help="Only process source with this name")
    parser.add_argument("--force", action="store_true", help="Regenerate even if exists")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temp files for debugging")
    args = parser.parse_args()

    # Clean up old temp dirs from interrupted runs
    cleanup_old_temp_dirs()

    sources = load_sources()

    # Filter to static sources only (not scan)
    static_sources = [s for s in sources if s["type"] != "scan"]

    if args.name:
        static_sources = [s for s in static_sources if s["name"] == args.name]
        if not static_sources:
            print(f"Error: No source found with name '{args.name}'")
            return 1

    # Check which need generation
    to_generate = []
    for s in static_sources:
        output_path = get_output_path(s["collection"], s["name"])
        if args.force or not output_path.exists():
            to_generate.append(s)

    if not to_generate:
        print("All static sources up to date.")
        return 0

    print(f"Found {len(to_generate)} source(s) to generate:")
    for s in to_generate:
        output_path = get_output_path(s["collection"], s["name"])
        status = "FORCE" if output_path.exists() else "NEW"
        print(f"  [{status}] {s['group']}/{s['collection']}/{s['name']} ({s['type']})")

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return 0

    # Initialize GDrive client and auth if needed
    global auth
    client = None
    needs_gdrive = any(s["type"] in ("file", "folder") for s in to_generate)
    if needs_gdrive:
        if not API_KEY:
            print("\nError: GOOGLE_API_KEY not set (required for GDrive sources)")
            return 1

        # Initialize auth for downloads
        auth = AuthManager()
        if auth.is_signed_in:
            print(f"Signed in as: {auth.user_email or 'user'}")
        else:
            print("Not signed in - attempting sign in for GDrive access...")
            if not auth.sign_in():
                print("Error: Sign-in required for GDrive downloads")
                return 1
            print("Sign-in successful!")

        client = DriveClient(DriveClientConfig(api_key=API_KEY), auth_token=auth.get_token())

    # Process each source
    failed = []
    for i, s in enumerate(to_generate, 1):
        print(f"\n[{i}/{len(to_generate)}] Processing {s['name']}...")

        temp_dir = Path(tempfile.mkdtemp(prefix="static_"))
        try:
            entry = process_source(
                source_type=s["type"],
                link=s["link"],
                name=s["name"],
                group=s["group"],
                collection=s["collection"],
                release_date=s.get("release_date"),
                client=client,
                temp_dir=temp_dir,
            )

            output_path = get_output_path(s["collection"], s["name"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(entry, indent=2))

            print(f"  -> {output_path}")
            print(f"     Downloads: {len(entry['downloads'])} ({entry['download_size'] / 1024 / 1024:.1f} MB)")
            print(f"     Extracted: {entry['file_count']} files ({entry['extracted_size'] / 1024 / 1024:.1f} MB)")
            print(f"     Charts: {entry['chart_count']}")

        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((s["name"], str(e)))

        finally:
            if not args.keep_temp:
                shutil.rmtree(temp_dir, ignore_errors=True)
            else:
                print(f"  Temp kept: {temp_dir}")

    if failed:
        print(f"\n{len(failed)} source(s) failed:")
        for name, err in failed:
            print(f"  - {name}: {err}")
        return 1

    print(f"\nDone. Generated {len(to_generate) - len(failed)} static source(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
