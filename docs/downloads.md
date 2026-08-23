# How downloads work, and why

Reference for anyone touching the download path. Distilled from the working notes
that drove the 2026 auth rework.

## The constraint

Synchotic's embedded Google OAuth client hit Google's 100-user lifetime cap.
Verification was submitted 2026-04-22 and came back requiring CASA Tier 2
(~$540/yr). The Tier 1 appeal was denied 2026-04-29.

The cap is lifetime and it is full, so **new users cannot sign in at all**. They
get "This app is blocked". This is permanent, not a queue we are waiting in.

Scanning is unaffected: it is API-key based and has no cap. Only authenticated
*downloads* are gated.

## Why that matters: measured, 2026-06-11

`scripts/measure_anon_failures.py` probed 1,272 files through the real anonymous
download path. Raw results in `anon_failure_results.json`.

| Bucket | Corpus | Blocked (count) | Blocked (bytes) |
|--------|--------|-----------------|-----------------|
| <10MB | 56,191 files / 74GB | ~0.8% | ~0.8% |
| 10-100MB | 8,305 files / 243GB | ~56% | ~67% |
| >100MB | 628 files / 117GB | ~97% | ~98% |

**~99% of files succeed anonymously, but ~63% of bytes are blocked**, concentrated
in exactly the high-demand content (Rock Band, Misc, Guitar Hero). Loose-chart
drives like BirdmanExe and Drummer's Monthly are essentially 100% anonymous.

The blocked set is only ~5,000-6,000 large files. Any fallback covers few files but
most bytes, so fallback speed is bandwidth-bound, not API-rate-bound.

Failure types: virus-scan interstitial dominates and kicks in well below 100MB
(`confirm=1` does not bypass it). Quota exhaustion is second and time-varying.

## The four tiers

Attempted in order per file, first success wins. Every tier produces identical
post-conditions (file at final path, marker written, partials cleaned), so
status.py, download_planner.py and purge_planner.py cannot tell them apart.

| Tier | Path | Who | Speed |
|------|------|-----|-------|
| 1 | Anonymous `uc?export=download` | Everyone | 24 workers, ~99% of file count |
| 2 | Embedded OAuth (`acknowledgeAbuse=true`) | Grandfathered signed-in users | 24 workers |
| 3 | BYOC credentials | Users who configured them | 24 workers, reuses tier 2 code |
| 4 | rclone `backend copyid` | Everyone else | One file at a time, see below |

**Grandfathered users never leave tier 2.** Tier 4 never fires and the rclone
binary is never downloaded. If their token dies they degrade to tier 4 rather than
being stranded.

Tier 4 receives exact file IDs from the live scan, never paths or folder listings,
so it pays no rescan cost and cannot hold a stale view. It is purely an
authenticated download pipe.

**Tier 4 is currently sequential.** `rclone/downloader.py download()` submits one
`copyid_async` and blocks on `_await_job` before the next, and no `--transfers` is
set. Throughput against the OAuth path has never been measured. See the backlog
entry before assuming it is fast or slow.

## Rejected, and why

- **CASA Tier 2 ($540/yr).** Buys only what rclone gives for free. Revisit if
  there is ever revenue.
- **R2 mirror ($4-7/mo).** Cost is not the issue. Mirroring ~116GB turns Synchotic
  from an index pointing at other people's Drive folders into a distributor, which
  is a licensing and DMCA surface we do not have today, and drive maintainers may
  object. Hard to walk back. Revisit if rclone friction proves painful and
  donations appear.
- **Service account.** The key would ship inside a desktop app, public on day one.
- **Anonymous-only with graceful degradation.** Dead on the measurement above.
  63% of bytes missing is a broken product for Rock Band and Guitar Hero users.
- **A new OAuth app to reset the cap.** This is cap evasion and Google enforces at
  project-owner level, so the downside is the existing app and account getting
  flagged, not just a denial.

## Worth re-checking

Google changes CASA tiering roughly every 6 months, so the current state may not be
permanent. If Synchotic ever gains donations, the R2 mirror becomes obvious.
