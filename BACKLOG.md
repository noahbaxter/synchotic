# Backlog

## Inbox

- [ ] [feature] Beta launcher channel *(2026-03-26, prompted by Treebear scan perf discussion)*
  - Rename dev launcher to "beta" for user-facing opt-in testing
  - New `release-launcher-beta.yml`, `RELEASE_TAG = "beta-latest"`, binaries `synchotic-launcher-beta`
  - Extracts to `.dm-sync/_app_beta/`, keep dev channel for internal testing

- [ ] [feature] Localization *(2026-03-29, Suc offering Japanese translation help)*
  - ~30 strings in TUI, low effort to externalize
  - Suc volunteered to coordinate translations, suggested Google Form for community submissions

## Active

- [ ] [ops] Google OAuth verification — hit 100 user cap, new users blocked *(2026-04-01)*
  - **Problem:** 100/100 lifetime unverified user cap reached. New users get "This app is blocked". No workaround — verification is the only fix.
  - Privacy policy: `PRIVACY.md` (drafted, needs commit + push so GitHub URL works)
  - Go to Verification Center in Google Auth Platform console
  - Add privacy policy URL: `https://github.com/noahbaxter/synchotic/blob/main/PRIVACY.md`
  - Record short screen capture of OAuth flow + how Drive data is used (unlisted YouTube)
  - Submit for verification — typically 1-2 weeks for sensitive (non-restricted) scopes

## Active Bugs

- [ ] [bug] Path length infinite loop - Windows files with paths >260 chars create endless retry cycle *(reported 2026-02-02, user "PILE")*
  - **Symptoms:** GUI shows "2.3GB to download" but nothing syncs, same files retry forever
  - **Root cause:** Files download but extraction fails with `WinError 206` (path too long), marker creation also fails, purge deletes partial files as "extra", next sync sees same files as missing
  - **Status:** Steps 1-4 of failed markers done (markers.py, downloader.py, download_planner.py have failed marker support). Remaining:
    - [ ] `purge_planner.py`: Don't purge files with failed markers
    - [ ] `home.py`: Show failed count in status ("562/562 synced, 5 failed (long paths)")

- [ ] [bug] Scan failure reporting is noisy and inaccurate *(noticed 2026-02-19)*
  - Warns about disabled setlists failing to scan — user doesn't care, they're disabled
  - Count says "26/26 scanned" even when 2 failed — should show "24/26" with failures indicated

## Needs Confirmation (likely fixed — close if no reports by v1.5)

- [ ] [bug] Custom folder sync deletes/corrupts charts *(reported 2026-01-27, Suc)* — likely fixed by c09553c (extraction flattening)
- [ ] [bug] Sync reports 100% but misses files *(Venxm)* — likely fixed by marker system
- [ ] [bug] Charts re-downloading despite 100% *(Splax)* — likely fixed by marker system + .ini tolerance

## Quick Wins

| Item | Effort | Impact |
|------|--------|--------|
| Purge planner failed marker protection | ~5 lines | Completes failed markers feature |
| Home.py failed count display | ~15 lines | Users see why archives failed |
| Remove state.py + migration code | Delete ~450 lines | Dead code (nothing imports it) |

## Testing Gaps

35 integration tests landed (195e318, 2930242). Remaining:
- [ ] Extracted archive purge safety (the 185GB scenario)
- [ ] Trailing spaces in filenames
- [ ] Extra files in failed setlist folders
- [ ] Per-setlist cache invalidation during sync/purge
- [ ] INI smaller than manifest should fail
- [ ] `delete_videos=False` path
- [ ] Background scanner failure handling (0 tests)
- [ ] Windows backslash in path lookups (platform-specific)

## Low Priority

- [ ] [bug] Google Drive incomplete response errors - intermittent `ContentLengthError` on large 7z files *(triaged 2026-01-26, hababa2)* — likely Google Drive issue, could add retry logic

- [ ] [low] Community Track Packs shows as 1 setlist — folder has 18 zips with no subfolders
  - Ask maintainer to reorganize, or add flat zip discovery mode (probably not worth it for one drive)

## Blocked / External

- [ ] [perf] Flat .sng drive structure for scan performance *(2026-03-29, discussed with Invontor)*
  - Current: each chart = folder of 4-8 loose files → scanner must list every folder → ~565 API calls for 2 setlists
  - Flat .sng: each chart = single file, no subfolders → ~1 list call per setlist
  - Invontor plans to recommend .sng + flat structure after v1.1 drops
  - Blocked on: community adoption, drive maintainers restructuring
  - No code changes needed on our side — scanner already handles both layouts

## Known Non-Issues

- **Scan API calls cannot be reduced by batching** *(researched 2026-02-03, confirmed 2026-03-29)*
  - FolderScanner already batches 100 folder listings per HTTP request (BFS level-by-level)
  - Cross-setlist batching was tested and is redundant — same API calls, more overhead, 2x slower
  - Real scan improvement requires fewer folders, not fewer HTTP requests
  - Flat .sng structure would drop ~565 calls/2 setlists to ~2-4 calls (one list per setlist)

- **Cross-drive duplicate chart detection not worth building** *(measured 2026-03-31)*
  - MD5-matched dupes across all 8 default drives: 251 charts / 3.5 GB / 0.9%
  - Clone Hero detects ~748 dupes on same drives (~2.8%) because it compares extracted chart content
  - Most user-reported dupes come from custom drives overlapping defaults or within-drive dupes (drive maintainer issue)
  - Script: `scripts/measure_overlap.py` — cached, rerunnable if drives change

## Icebox

- [ ] [feature] Static sources refactor - serve CDN files for official setlists *(captured 2026-01-26)*
  - Prior attempts: v1 (over-engineered), v2 (got stuck), v3 (incomplete but closest)
  - To resume v3: `git checkout sources-refactor-v3 && git reset HEAD~1`

- [ ] [feature] Shareable pack "codes" - generate codes to share custom drive lists *(Invontor)*

- [ ] [idea] Add CSC chart drops to official manifest *(xez/highfine)*

- [ ] [feature] Archive content indexing for static drives *(captured 2026-01-30)*
  - Pre-index file contents of archives for fixed drives (Guitar Hero, Rock Band)
  - Manifest currently counts archives, not extracted charts — "Rocks the 80s" shows "1 chart" but extracts to 39

- [ ] [idea] Obfuscate drive links via GitHub secrets *(discussed but unclear if wanted)*

## Version History

### v1.4.0 (released)
New community drives (CSC Released Packs, Community Track Packs, Popular Charters), drive groups in UI, no default drives enabled (empty hint prompts users), macOS code signing for launcher, README rewrite, updated screenshot.

### v1.3.4 (released)
Empty file sync loop fix, restored custom folder subfolder toggles.

### v1.3.3 (released)
Failed markers for path-length extraction failures, archive MD5 update detection, integration tests for purge/path/cache edge cases, dead script cleanup.

### v1.3.2 (released)
Granular cache invalidation, purge safety confirmation, per-setlist purge cache invalidation, disk size display fixes.

### v1.3.1 (released)
Windows long path fixes, dev release channel, path sanitization at scanner source, scan caching.

### v1.3.0 (released)
Lazy scanning with background scanner, direct API scanning (replaced manifest fetch), per-setlist sync, marker-based sync (SyncState removed), UI overhaul (themes, buffered rendering, key coalescing, sync deltas).

### v1.2.6 (released)
Progress display duplicate lines, song.ini re-download fix, cancel sync improvements.

### v1.2.2 (released)
Status/planner disagreement fixes, disk fallback bugs, NFC normalization, marker system, .zip extraction with subdirectories, loose file size checking.
