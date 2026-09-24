# Backlog

## Inbox

- [ ] [cleanup] remove adopted data from the old `.dm-sync` beside the Windows exe *(2026-09-24)*
  - 1.5.5 copies settings, token, rclone config, caches, logs and markers into the OS dirs and leaves the originals, as the fallback if an adoption goes wrong in the field.
  - Once 1.5.5 upgrades are confirmed, delete on a later launch only what provably arrived: each file present at its destination, and every marker present in the library. A marker deleted before it arrived turns its charts into purge extras. Purge-adjacent, so manual verification.
  - Never `_app`, `wezterm` or launcher logs: launcher 1.3 still runs from there, so the folder itself stays until people have a newer launcher.

- [ ] [feature] let the app update the launcher *(2026-09-24)*
  - The app updates every run, the launcher never does, and there is no channel to tell people to download it again. Launcher-side changes (e.g. the OS-dirs layout in `eb19d72`) reach nobody until they do.
  - The app knows when launcher 1.3 started it (frozen Windows, `SYNCHOTIC_ROOT` set). Windows will not overwrite a running exe, and the 1.3 launcher waits on the app, so it would have to rename the old exe aside and drop the new one in place.

- [ ] [ux] first-run gaps left from the Discord thread *(2026-09-12, #ask-anything)*
  - Guided setup, checks on every launch, the unowned-library warning and the library row confusion all landed after 1.5.4. What is left:
  - **"Which drives?" recommendations.** Three toggles, one per top-level category (drums, guitar/community, official game setlists), each flipping its whole group. The community tab is mostly guitar charts, so a drummer who enables everything gets hundreds of GB they never wanted.
  - **BYOC consent screen.** Google will not publish it until its fields are filled, and the user did not see the defaults in `docs/byoc.md`. Call them out where the form is described.
  - **Set expectations.** A first full sync runs for hours (reported ~8h). Say so up front.
  - **Manual downloads.** The ready page says sync matches the drives exactly, but not that manually downloaded copies of the same charts become duplicates, or that scores are untouched unless a chart updates.
  - Icebox candidate: help users find charts that duplicate synced ones (one user had ~4k dupes).

- [ ] [bug] turning a type back on does not re-extract packs already extracted *(2026-08-29)*
  - Add `*.mp4` to `download_ignore`, sync, then take it out again: loose videos come down on the next sync, but ones inside an archive do not. The marker says the pack is synced, so `is_archive_synced` never re-extracts it, and the file stripped at extraction time stays gone until the pack's md5 changes.
  - Pinned as-is by `tests/integration/test_download_ignore_loop.py::test_an_archive_already_extracted_is_left_as_extracted`, so a fix has to change that test deliberately.
  - Fix would be to notice that `download_ignore` shrank and re-extract affected packs, which means recording the list a marker was written under. Not obviously worth it.

- [ ] [bug] purge_ignore cannot spare a folder *(2026-08-29)*
  - `matches_ignore` (`core/files.py:10`) fnmatches the filename only, so `MyCustoms/*` matches nothing and there is no way to tell purge to leave a folder of hand-made charts alone.
  - Match the relative path as well as the filename. `download_ignore` and `purge_ignore` share that matcher, so a folder pattern would start working for both at once. Check what that means for downloads before doing it.

- [ ] [bug] a relocated AppImage cannot find the install it came from *(2026-08-29)*
  - `portable_dir()` in `launcher.py` answers "the folder the AppImage sits in", which is where adoption looks for a previous install. AppImageLauncher moves AppImages into `~/Applications`, so for anyone who accepts its prompt the old install is never found and the upgrade reads as a factory reset.
  - Hit in the field on 2026-08-28. The user recovered by hand-copying settings.json, token.json and credentials.json into `~/.local/share/synchotic`.
  - A defaults-only settings file no longer counts as an install, so a launch that *can* see the old folder adopts it. This is the other half, finding the folder at all: add `~/Applications` to `legacy_install_candidates()`, or ask the desktop entry where it was launched from.

- [ ] [linux] AppImage ships an icon nothing renders *(2026-08-28)*
  - `build_launcher_appimage.sh` says the AppImage carries its .desktop entry and icon, so the launcher need not write them into ~/.local/share. Only half true.
  - On Fedora 44 / KDE there is no AppImage thumbnailer, and neither plasmashell nor dolphin reads `.DirIcon`. The icon users see comes from `~/.local/share/icons`, written by `ensure_linux_desktop()` on first run.
  - Cosmetic. Either fix the comment or accept that a `.desktop` launcher is the only way to get the logo on a Plasma desktop.

- [ ] [risk] rebuild_markers_from_disk can mark charts synced that were never downloaded *(2026-08-28)*
  - For an archive with no marker it rglobs the whole setlist folder and writes a marker claiming every file in it. An archive that was never fetched into an already-populated setlist therefore reads as synced and is never downloaded.
  - Deliberate, and `tests/integration/test_partial_operations.py` asserts it. It is the trade against mass deletion.
  - Logged so the trade is a decision rather than a surprise. Silent missing charts are the cost.

- [ ] [perf] rclone tier downloads one file at a time *(2026-08-23)*
  - `rclone/downloader.py download()` submits one `copyid_async` then blocks on `_await_job` before the next. Tiers 1-3 run 24 workers (`sync/downloader.py:72`). No `--transfers` is set anywhere either.
  - `docs/downloads.md` records the tier table and states tier 4 is sequential. Update it with real numbers once measured.
  - **Measure before fixing.** `RCLONE_SMOKE_CHECKLIST.md` section 4 was never run. Do one Rock Band sync, compare wall-clock to the OAuth path. If a single stream already saturates the link, sequential costs nothing and this is a doc fix only.
  - If the gap is real: hold N jobs in flight (`copyid_async` already returns a job id) and poll together. Then re-run the tier-4 trust invariant, because concurrent jobs share the temp dir that `_reconcile` diffs.
  - Not a correctness issue. Files arrive intact, verified byte-identical. Slow beats blocked.

- [ ] [testing] BYOC has never run end to end *(2026-08-23)*
  - Coverage is 3 unit tests on `load_client_config()` precedence plus one tier-4-skip case. Nobody has created a real Cloud project, dropped in `credentials.json`, signed in, and pulled a blocked file.
  - Guardrail shipped in v1.5 (`has_custom_client_config`), so picking BYOC without credentials now warns instead of silently signing in with the blocked shared client. The happy path is still unverified.
  - `docs/byoc.md` still frames BYOC as being about speed and quota ("if you just want it to work you do not need this"). That is pre-rejection framing. For a new user the shared client does not work at all.
  - Chooser copy says BYOC is "just as fast" as rclone. Given tier 3 is 24 workers and tier 4 is sequential, BYOC is faster. Reword once the throughput measurement above exists.

- [ ] [cleanup] rip out the remote manifest pipeline *(2026-09-24)*
  - The app scans drives itself and never reads the `manifest` release. Only dev tooling does: `manifest_gen.py`, `src/manifest/`, `src/drive/changes.py`, `.github/workflows/update-manifest.yml`, and `scripts/measure_anon_failures.py` / `measure_overlap.py`, ~2.1k lines.
  - Nightly cron stays off: it bought nothing and a dead `GOOGLE_TOKEN` secret would fail it every night.
  - Keep until the measurement scripts are no longer wanted, since the blocked-rate numbers in `docs/downloads.md` came from them. `src/stats/` and `manifest_overrides.json` are app code, not part of this.

- [ ] [cleanup] finish chotic-ui `fix/menu-text-wrapping` *(2026-08-23)*
  - The wrapping fix (`99e9a5a`) is in chotic-ui `main`. `c3bce2f` (a real grey for disabled rows instead of the dim attribute) is not. Merge it or delete the branch.

- [ ] [bug] stale markers are never deleted, so updated packs leak charts *(2026-08-23)*
  - `markers.py` defines `delete_marker` (192), `delete_markers_for_archive` (278) and `delete_failed_markers_for_archive` (391). **None of the three is called anywhere in `src/`.**
  - Markers key on `(archive_path, md5)`. When a pack updates, `downloader.py:419` writes a marker for the new md5 and the old one stays forever. Purge treats every marker's file list as protected, so charts the updated pack renamed or dropped are never reclaimed.
  - Fails safe (keeps files rather than deleting them) and predates v1.5, so not a release blocker.
  - Purge-adjacent, so per the repo instructions this needs manual verification, not just unit tests.

- [ ] [ux] failed charts vanish from the count with no explanation *(2026-08-23)*
  - `status.py:147` continues before `total_charts += 1`, so a permanently failed archive leaves both the numerator and the denominator. The sync reads a clean 100% while the charts are simply absent.
  - `download_planner.py:139` correctly skips them, so nothing loops. This is purely "the user is never told".
  - `MainMenuCache` has no failed field, so this is nearer 30-40 lines than the 15 estimated earlier. Count via `get_all_failed_markers()`, add a cache field, render it in the home status line.

- [ ] [cleanup] delete the dead SyncState path *(2026-08-23)*
  - `src/sync/state.py` is 420 lines and nothing in `src/` imports it.
  - `markers.py:530-615 migrate_sync_state_to_markers` is likewise only ever called from `tests/test_markers.py`. The whole SyncState to markers migration is already unreachable in production, so a v1.2-era upgrade gets no migration today either way. Deleting it changes no behavior.
  - Roughly 500 lines plus the tests that exist only to cover it.

- [ ] [bug] redirecting output on Windows crashes the TUI *(2026-08-23)*
  - `menu.py _render` writes the frame to `sys.__stdout__`. Against a real console Python routes through WriteConsoleW and any Unicode works, but a redirect (`synchotic.exe > out.txt`) hands it a cp1252 pipe and the rounded box characters raise `UnicodeEncodeError`.
  - **Pre-existing, not a regression.** Identical code in v1.4 at `277df5c:src/ui/widgets/menu.py:524`.
  - The launcher is unaffected: `launcher.py:701` uses `subprocess.run(args, env=env)` with no `stdout=`, so the app inherits the console handle rather than a pipe.
  - Surfaced by CI when the new render test ran on Windows for the first time. The test now renders into a StringIO, so it no longer depends on console encoding.
  - Fix would be to reconfigure to utf-8 with `errors="replace"` when stdout is not a tty.

- [ ] [feature] Beta launcher channel *(2026-03-26, prompted by Treebear scan perf discussion)*
  - Rename dev launcher to "beta" for user-facing opt-in testing
  - New `release-launcher-beta.yml`, `RELEASE_TAG = "beta-latest"`, binaries `synchotic-launcher-beta`
  - Extracts to `.dm-sync/_app_beta/`, keep dev channel for internal testing

- [ ] [feature] Localization *(2026-03-29, Suc offering Japanese translation help)*
  - ~30 strings in TUI, low effort to externalize
  - Suc volunteered to coordinate translations, suggested Google Form for community submissions

## Active

- [ ] [ops] rclone's shared client id is being retired, so rclone mode has an expiry date *(2026-09-20)*
  - Google will charge for requests through rclone's built-in Drive client id, so rclone will disable and then remove it after ~90 days notice. Tracking issue, no date yet: https://github.com/rclone/rclone/issues/9580
  - After removal an rclone remote needs the user's own client id: the same Cloud project and copy-paste as BYOC, on a sequential pipe. rclone stops being the easy option.
  - No free "just sign in" path exists (checked 2026-09-20). Reading other people's shared folders needs a restricted scope, and `drive.file` via the Google Picker does not grant a folder's contents. The choice is CASA Tier 2 (~$540/yr) or every user brings credentials. A money decision, not an engineering one.
  - **Done:** the chooser labels rclone "(easiest)" and marks it deprecated, and labels BYOC "(best)". rclone stays available while it works.
  - **Trigger: rclone starts its 90-day notice.** Then decide CASA vs BYOC for everyone, and reframe `docs/byoc.md` (it still says most people do not need it). Open option: inject the user's own client id into the rclone remote instead of native BYOC.
  - Full notes: [docs/downloads.md](docs/downloads.md)

- [ ] [ops] Google OAuth verification blocked, shipping three-tier auth instead *(decided 2026-08-09)*
  - 100/100 unverified user cap reached. Verification submitted 2026-04-22, came back requiring CASA Tier 2 (~$540/yr). Tier 1 appeal denied 2026-04-29.
  - Anonymous failure rate measured 2026-06-11: ~99% of small files succeed, ~63% of bytes blocked (RB/GH rips, big Misc packs). Re-read 2026-08-09: 637/1272 sampled files are `virus_scan` (50% by count) and all 5 measured drives contain blocked files, so every user hits this on their first sync.
  - **Decision: ship the choice, not a single strategy.** Setup screen offers rclone (recommended) / anonymous / BYOC. No single option is right for every user, which is why this sat deferred since June.
  - **Rejected, R2 mirror ($4-7/mo):** cost is not the issue. Mirroring ~116 GB turns Synchotic from an index that points at other people's Drive folders into a distributor, which is a licensing/DMCA surface we don't have today and drive maintainers may object to. Hard to walk back. Reconsider only if rclone rate limits prove unusable (gauntlet step 3 will tell us).
  - **Rejected, CASA Tier 2 ($540/yr):** buys only what rclone gives for free. Revisit if there's ever revenue.
  - **Rejected, service account:** key would ship inside a desktop app, public on day one.
  - **Parked, new OAuth app to reset the cap:** this is cap evasion and Google enforces at project-owner level, so the downside is the existing app and account getting flagged, not just a denial. Weigh against 100 more users before trying.
  - **Measurements, the four tiers, and every rejected option: see [docs/downloads.md](docs/downloads.md)**
  - The `legacy-rclone` branch (commit `1435ab9`) stays up for people still on it, but the README no longer mentions it.

## Active Bugs

- [ ] [bug] Path length infinite loop - Windows files with paths >260 chars create endless retry cycle *(reported 2026-02-02, user "PILE")*
  - **Symptoms:** GUI shows "2.3GB to download" but nothing syncs, same files retry forever
  - **Root cause:** Files download but extraction fails with `WinError 206` (path too long), marker creation also fails, purge deletes partial files as "extra", next sync sees same files as missing
  - The library now opts out of MAX_PATH on Windows (`f4dcbc2`), which should remove the trigger. Confirm with PILE before closing.
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
