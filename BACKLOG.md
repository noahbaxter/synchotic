# Backlog

## Inbox

- [ ] [perf] rclone tier downloads one file at a time *(2026-08-23)*
  - `rclone/downloader.py download()` submits one `copyid_async` then blocks on `_await_job` before the next. Tiers 1-3 run 24 workers (`sync/downloader.py:72`). No `--transfers` is set anywhere either.
  - `RCLONE_WRAP_DESIGN.md:35` claims tier 4 is "~4-16 concurrent transfers". It is not. Fix the doc either way.
  - **Measure before fixing.** `RCLONE_SMOKE_CHECKLIST.md` section 4 was never run. Do one Rock Band sync, compare wall-clock to the OAuth path. If a single stream already saturates the link, sequential costs nothing and this is a doc fix only.
  - If the gap is real: hold N jobs in flight (`copyid_async` already returns a job id) and poll together. Then re-run the tier-4 trust invariant, because concurrent jobs share the temp dir that `_reconcile` diffs.
  - Not a correctness issue. Files arrive intact, verified byte-identical. Slow beats blocked.

- [ ] [testing] BYOC has never run end to end *(2026-08-23)*
  - Coverage is 3 unit tests on `load_client_config()` precedence plus one tier-4-skip case. Nobody has created a real Cloud project, dropped in `credentials.json`, signed in, and pulled a blocked file.
  - Guardrail shipped in v1.5 (`has_custom_client_config`), so picking BYOC without credentials now warns instead of silently signing in with the blocked shared client. The happy path is still unverified.
  - `docs/byoc.md` still frames BYOC as being about speed and quota ("if you just want it to work you do not need this"). That is pre-rejection framing. For a new user the shared client does not work at all.
  - Chooser copy says BYOC is "just as fast" as rclone. Given tier 3 is 24 workers and tier 4 is sequential, BYOC is faster. Reword once the throughput measurement above exists.

- [ ] [cleanup] merge chotic-ui `fix/menu-text-wrapping` into its main *(2026-08-23)*
  - v1.5 pins the submodule to a branch off `3f37d1e`, deliberately, to keep 3 unrelated chotic-ui commits (FilterList sizing, Tab MenuResult, FilterList section headers) out of a release whose TUI was untested.
  - After v1.5 ships: merge the fix into chotic-ui `main`, then bump the submodule to pick up the other three.
  - stemchotic is the other consumer. It sets no `MenuItem.description` and uses short subtitles, so it is unaffected either way.

- [ ] [feature] Beta launcher channel *(2026-03-26, prompted by Treebear scan perf discussion)*
  - Rename dev launcher to "beta" for user-facing opt-in testing
  - New `release-launcher-beta.yml`, `RELEASE_TAG = "beta-latest"`, binaries `synchotic-launcher-beta`
  - Extracts to `.dm-sync/_app_beta/`, keep dev channel for internal testing

- [ ] [feature] Localization *(2026-03-29, Suc offering Japanese translation help)*
  - ~30 strings in TUI, low effort to externalize
  - Suc volunteered to coordinate translations, suggested Google Form for community submissions

## Active

- [ ] [ops] Google OAuth verification blocked, shipping three-tier auth instead *(decided 2026-08-09)*
  - 100/100 unverified user cap reached. Verification submitted 2026-04-22, came back requiring CASA Tier 2 (~$540/yr). Tier 1 appeal denied 2026-04-29.
  - Anonymous failure rate measured 2026-06-11: ~99% of small files succeed, ~63% of bytes blocked (RB/GH rips, big Misc packs). Re-read 2026-08-09: 637/1272 sampled files are `virus_scan` (50% by count) and all 5 measured drives contain blocked files, so every user hits this on their first sync.
  - **Decision: ship the choice, not a single strategy.** Setup screen offers rclone (recommended) / anonymous / BYOC. No single option is right for every user, which is why this sat deferred since June.
  - **Rejected, R2 mirror ($4-7/mo):** cost is not the issue. Mirroring ~116 GB turns Synchotic from an index that points at other people's Drive folders into a distributor, which is a licensing/DMCA surface we don't have today and drive maintainers may object to. Hard to walk back. Reconsider only if rclone rate limits prove unusable (gauntlet step 3 will tell us).
  - **Rejected, CASA Tier 2 ($540/yr):** buys only what rclone gives for free. Revisit if there's ever revenue.
  - **Rejected, service account:** key would ship inside a desktop app, public on day one.
  - **Parked, new OAuth app to reset the cap:** this is cap evasion and Google enforces at project-owner level, so the downside is the existing app and account getting flagged, not just a denial. Weigh against 100 more users before trying.
  - **Full status, measurement data, and implementation plans: see [OAUTH_PLAN.md](OAUTH_PLAN.md)**
  - Workaround live: `legacy-rclone` branch (commit `1435ab9`). README has a callout pointing blocked users there.

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
- [ ] Windows, end to end. Never tested, and it is where most users are. Covers the whole v1.5 auth path, not just one screen.
- [ ] Windows: confirm a freshly downloaded unsigned `rclone.exe` is not quarantined by Defender/SmartScreen (`RCLONE_SMOKE_CHECKLIST.md` section 2).
- [ ] Windows: `reap_stale` uses `ps`, POSIX-only, so a crashed rcd daemon is not reaped. Verify no orphan `rclone.exe` lingers after a normal run.
- [ ] Render-level UI tests exist only for the first-run chooser (`tests/ui/test_download_mode_render.py`). Every other screen is still asserted through a stubbed `Menu.run`, which is exactly how the chooser shipped broken: the tests checked `MenuItem` data that never reached the screen.

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
