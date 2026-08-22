"""Measure how many manifest files fail anonymous (no-auth) download.

Replicates the downloader's anonymous path exactly (uc?export=download&confirm=1,
retry on HTML up to 3 attempts) and reports failure rate by file count and bytes,
broken down by failure type, size bucket, and setlist.

Usage:
    python scripts/measure_anon_failures.py                  # stratified sample
    python scripts/measure_anon_failures.py --full           # every file (slow)
    python scripts/measure_anon_failures.py --per-setlist 50 --concurrency 4
"""

import argparse
import asyncio
import json
import random
import ssl
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

import urllib.request

import aiohttp

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core.formatting import format_size
from src.core.paths import get_certifi_ssl_context

MANIFEST_URL = "https://github.com/noahbaxter/synchotic/releases/download/manifest/manifest.json"

DOWNLOAD_URL_TEMPLATE = "https://drive.google.com/uc?export=download&id={file_id}&confirm=1"
MAX_RETRIES = 3  # mirrors FileDownloader.max_retries
LARGE_FILE = 100_000_000  # virus-scan interstitial territory; always measured
TIMEOUT = aiohttp.ClientTimeout(connect=10, sock_read=60)

SIZE_BUCKETS = [
    ("<10MB", 0, 10_000_000),
    ("10-100MB", 10_000_000, 100_000_000),
    (">100MB", 100_000_000, float("inf")),
]


@dataclass
class Result:
    folder: str
    path: str
    file_id: str
    size: int
    outcome: str  # ok | virus_scan | quota | html_other | not_found | forbidden | rate_limited | error
    detail: str = ""


def bucket_for(size: int) -> str:
    for name, lo, hi in SIZE_BUCKETS:
        if lo <= size < hi:
            return name
    return SIZE_BUCKETS[-1][0]


def classify_html(snippet: str) -> tuple[str, str]:
    text = snippet.lower()
    if "virus" in text or "download anyway" in text:
        return "virus_scan", "virus scan interstitial"
    if "too many users" in text or "quota" in text or "exceeded" in text:
        return "quota", "download quota exceeded"
    return "html_other", "unrecognized HTML response"


def sample_files(manifest: dict, per_setlist: int, full: bool, seed: int) -> list[dict]:
    """All large files always included; smaller files sampled per setlist."""
    rng = random.Random(seed)
    selected = []
    for folder in manifest.get("folders", []):
        files = [f for f in folder.get("files", []) if f.get("id")]
        for f in files:
            f["_folder"] = folder.get("name", "?")
        if full:
            selected.extend(files)
            continue
        large = [f for f in files if f.get("size", 0) >= LARGE_FILE]
        small = [f for f in files if f.get("size", 0) < LARGE_FILE]
        selected.extend(large)
        selected.extend(rng.sample(small, min(per_setlist, len(small))))
    return selected


async def probe(session: aiohttp.ClientSession, sem: asyncio.Semaphore, f: dict) -> Result:
    url = DOWNLOAD_URL_TEMPLATE.format(file_id=f["id"])
    base = dict(folder=f["_folder"], path=f.get("path", f.get("name", "?")),
                file_id=f["id"], size=f.get("size", 0))
    async with sem:
        for attempt in range(MAX_RETRIES):
            try:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status == 404:
                        return Result(**base, outcome="not_found", detail="404 (stale manifest?)")
                    if resp.status == 403:
                        return Result(**base, outcome="forbidden", detail="403")
                    if resp.status == 429:
                        return Result(**base, outcome="rate_limited", detail="429")
                    resp.raise_for_status()

                    if "text/html" in resp.headers.get("content-type", ""):
                        # Same retry behavior as the real downloader before giving up
                        if attempt < MAX_RETRIES - 1:
                            snippet = (await resp.content.read(4096)).decode("utf-8", "replace")
                            await asyncio.sleep(1.0 * (attempt + 1))
                            continue
                        snippet = (await resp.content.read(4096)).decode("utf-8", "replace")
                        outcome, detail = classify_html(snippet)
                        return Result(**base, outcome=outcome, detail=detail)

                    # Real file content: read one chunk to confirm, then bail
                    await resp.content.read(8192)
                    return Result(**base, outcome="ok")
            except asyncio.TimeoutError:
                if attempt == MAX_RETRIES - 1:
                    return Result(**base, outcome="error", detail="timeout")
                await asyncio.sleep(1.0 * (attempt + 1))
            except aiohttp.ClientError as e:
                if attempt == MAX_RETRIES - 1:
                    return Result(**base, outcome="error", detail=str(e)[:120])
                await asyncio.sleep(1.0 * (attempt + 1))
    return Result(**base, outcome="error", detail="exhausted retries")


def report(results: list[Result], sampled_from: int):
    # 404s are manifest staleness, not anonymous-access failures: exclude from rates
    measured = [r for r in results if r.outcome != "not_found"]
    blocked = [r for r in measured if r.outcome not in ("ok", "error")]
    errored = [r for r in measured if r.outcome == "error"]
    total_bytes = sum(r.size for r in measured)
    blocked_bytes = sum(r.size for r in blocked)

    print(f"\n{'=' * 62}")
    print(f"Probed {len(results)} files (of {sampled_from} in manifest)")
    nf = len(results) - len(measured)
    if nf:
        print(f"  {nf} returned 404 (stale manifest), excluded from rates")
    if errored:
        print(f"  {len(errored)} network errors, counted as neither ok nor blocked")

    def pct(n, d):
        return f"{100 * n / d:.1f}%" if d else "n/a"

    print(f"\nBLOCKED anonymously: {len(blocked)}/{len(measured)} files ({pct(len(blocked), len(measured))})")
    print(f"                     {format_size(blocked_bytes)}/{format_size(total_bytes)} bytes ({pct(blocked_bytes, total_bytes)})")

    print("\nBy failure type:")
    for outcome, count in Counter(r.outcome for r in blocked).most_common():
        b = sum(r.size for r in blocked if r.outcome == outcome)
        print(f"  {outcome:<14} {count:>6} files  {format_size(b):>10}")

    print("\nBy size bucket:")
    for name, _, _ in SIZE_BUCKETS:
        in_bucket = [r for r in measured if bucket_for(r.size) == name]
        bad = [r for r in in_bucket if r in blocked]
        bb = sum(r.size for r in bad)
        tb = sum(r.size for r in in_bucket)
        print(f"  {name:<10} {len(bad):>6}/{len(in_bucket):<6} files blocked ({pct(len(bad), len(in_bucket))}), "
              f"{format_size(bb)}/{format_size(tb)} bytes ({pct(bb, tb)})")

    print("\nBy setlist:")
    for folder in sorted({r.folder for r in measured}):
        in_f = [r for r in measured if r.folder == folder]
        bad = [r for r in in_f if r in blocked]
        bb = sum(r.size for r in bad)
        print(f"  {folder:<40} {len(bad):>5}/{len(in_f):<5} blocked, {format_size(bb)} affected")

    # The number that prices the fallback mirror: storage for blocked bytes only.
    # Sampled rate extrapolates by bucket; >100MB files are probed exhaustively.
    print(f"\nSelective R2 mirror estimate (blocked bytes at $0.015/GB-mo): "
          f"${blocked_bytes / 1e9 * 0.015:.2f}/mo for the probed set")
    print("=" * 62)


async def run(files: list[dict], concurrency: int) -> list[Result]:
    sem = asyncio.Semaphore(concurrency)
    ssl_context = ssl.create_default_context(cafile=get_certifi_ssl_context())
    connector = aiohttp.TCPConnector(limit=concurrency, ssl=ssl_context)
    done = 0
    results = []
    async with aiohttp.ClientSession(timeout=TIMEOUT, connector=connector) as session:
        for coro in asyncio.as_completed([probe(session, sem, f) for f in files]):
            results.append(await coro)
            done += 1
            if done % 25 == 0 or done == len(files):
                print(f"\r  {done}/{len(files)} probed...", end="", flush=True)
    print()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", action="store_true", help="probe every file instead of sampling")
    parser.add_argument("--per-setlist", type=int, default=150,
                        help="files <100MB sampled per setlist (default 150); >100MB always all probed")
    parser.add_argument("--concurrency", type=int, default=8,
                        help="concurrent probes (default 8; keep low to avoid self-inflicted rate limits)")
    parser.add_argument("--seed", type=int, default=42, help="sampling seed for reproducibility")
    parser.add_argument("--manifest", type=Path, help="local manifest.json (default: fetch from GitHub release)")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "anon_failure_results.json",
                        help="where to write raw per-file results JSON")
    args = parser.parse_args()

    if args.manifest:
        manifest = json.loads(args.manifest.read_text())
    else:
        print(f"Fetching manifest from {MANIFEST_URL}")
        with urllib.request.urlopen(MANIFEST_URL) as resp:
            manifest = json.load(resp)
        print(f"Manifest generated: {manifest.get('generated', '?')}")

    total_files = sum(len(f.get("files", [])) for f in manifest.get("folders", []))
    files = sample_files(manifest, args.per_setlist, args.full, args.seed)
    print(f"Probing {len(files)} of {total_files} files "
          f"({'full' if args.full else f'all >100MB + {args.per_setlist}/setlist sample'}), "
          f"concurrency {args.concurrency}")

    results = asyncio.run(run(files, args.concurrency))
    report(results, total_files)

    args.output.write_text(json.dumps([asdict(r) for r in results], indent=2))
    print(f"\nRaw results: {args.output}")


if __name__ == "__main__":
    main()
