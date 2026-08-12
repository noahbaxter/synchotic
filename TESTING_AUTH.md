# Manual auth-mode test checklist (release gate)

The 431 automated tests mock every Google network call, so they prove the plumbing, not that real auth works. This checklist proves the 4 sign-in modes work end to end against real Drive. Run it before a release and whenever the rclone pin is bumped. Companion to `RCLONE_SMOKE_CHECKLIST.md` (which covers the raw rclone commands).

## The 4 download tiers

Per file, tried in order, first success wins:

1. **anonymous**: no auth, carries ~99% of files by count
2. **oauth**: embedded Synchotic OAuth (grandfathered signed-in users) OR your own BYOC credentials, same code path, different client
3. (BYOC is tier 2 with your own client, listed separately below because it is set up differently)
4. **rclone**: automatic, one Google consent click, fetches the virus-scan-blocked large archives

## Setup

Run from this branch so you test this code:

```bash
cd ../synchotic-worktrees/rclone-download-tier
/Users/noahbaxter/Code/personal/charting/synchotic/.venv/bin/python sync.py
```

**Proof of which tier delivered each file** is logged automatically. Every successful download writes a `TIER | <tier> | <filename>` line to the daily log at `.dm-sync/logs/YYYY-MM-DD.log`. After a sync:

```bash
grep "TIER |" .dm-sync/logs/$(date +%Y-%m-%d).log
# TIER | anonymous | small_chart.zip
# TIER | oauth | big_pack.7z
# TIER | rclone | RockBand_rip.7z
```

This is the one-glance proof: you see exactly which path delivered each file, not just that it arrived.

**Observable file evidence** under `.dm-sync/`:
- `token.json`: exists only when signed in (tier 2 embedded or tier 3 BYOC)
- `credentials.json` or `SYNCHOTIC_OAUTH_*` env vars: present only for BYOC (tier 3)
- `rclone/rclone.conf` + `rclone/rclone` binary: created only when the rclone tier is set up
- a live `rclone` process during sync (`ps aux | grep rclone`): unambiguous proof tier 4 is downloading

**Force an auth tier to fire**: you need a *blocked* file. The threshold is well under 100MB. The smallest measured one is 26.3MB (`anon_failure_results.json`, measured 2026-06-11), so a single mode costs ~26MB of data, not gigabytes. The Misc, Rock Band, and Guitar Hero drives have them. Small loose-file drives (Birdman, Drummer's Monthly) download anonymously and never exercise auth.

**Two different failure classes, do not confuse them.** Of 754 anonymous failures measured:

| outcome | count | what it means | does auth fix it |
|---|---|---|---|
| `virus_scan` | 637 | Google's virus-scan interstitial | yes, this is what tiers 2-4 exist for |
| `quota` | 111 | download quota exceeded | no, retry later |

Gauntlet step 3 depends entirely on telling these apart. Example `virus_scan` file: `Tonic - If You Could Only See_RB4DLCtoINI.zip` (26.3MB). Example `quota` file: `RBN 191.7z` (8.1MB), though quota state resets so it may succeed today.

## Automated harness

`scripts/manual_auth_test.py` automates everything below except the browser clicks. It runs against a `mkdtemp()` root via `SYNCHOTIC_ROOT`, syncs a pinned 4-file fixture (one 26.3MB blocked archive, three tiny loose files), and asserts the delivering tier, the trust invariant, and the auth-artifact matrix.

```bash
scripts/build_test_fixture.py                      # refresh pinned ids, metadata only
scripts/manual_auth_test.py --mode anonymous       # ~31 KB
scripts/manual_auth_test.py --mode oauth           # ~26 MB
scripts/manual_auth_test.py --mode byoc            # ~26 MB
scripts/manual_auth_test.py --mode rclone --keep /tmp/sc-authtest   # ~26 MB + binary
```

Run the harness first. Use the manual modes below to cover what it cannot: the consent explainer screen, the menu sign-in flow, and the Google consent page branding.

**Reset between modes** so each test starts clean:

```bash
rm -f .dm-sync/token.json .dm-sync/credentials.json
rm -rf .dm-sync/rclone
unset SYNCHOTIC_OAUTH_CLIENT_ID SYNCHOTIC_OAUTH_CLIENT_SECRET
```

## Modes

### Mode 1: anonymous only

> **There is currently no way to decline.** `folder_sync.py:165-168` prints
> `display.rclone_consent_explainer()` and then calls `ensure_authed()`, which opens the
> browser. The explainer is print-only (`sync_display.py:75-82`), it has no prompt and no
> return value. The only "decline" available to a user is closing the browser tab. Fix
> that before shipping, then update this mode.

- [ ] Reset. Do not sign in. Close the browser tab when rclone consent opens. Sync a drive with big archives.
- Expect: small files succeed, big archives report `NEEDS AUTH (...)` and are skipped.
- Prove: log shows only `TIER | anonymous | ...`; no `token.json`, no `rclone/`, no rclone process. Blocked files visibly fail. (Confirms tier 1 works and blocking is detected.)

### Mode 2: embedded OAuth (grandfathered)
- [ ] Reset. Sign in via the menu with your existing grandfathered Google account. Sync.
- Expect: big archives download.
- Prove: log shows `TIER | oauth | ...` for the big archives; `token.json` exists; NO `rclone/` dir, NO rclone process (tier 2 caught them before tier 4). (Confirms existing users are unaffected.)

### Mode 3: BYOC
- [ ] Reset. Set up your own GCP credentials per `docs/byoc.md`, drop `credentials.json` in `.dm-sync/` (or export the env vars), sign in. Sync.
- Expect: big archives download at full speed.
- Prove: log shows `TIER | oauth | ...`; `token.json` and `credentials.json` present; no rclone process. Confirm the browser consent screen showed YOUR project name, not Synchotic's.

### Mode 4: rclone (the new path)
- [ ] Reset. Do not sign in. When the consent explainer appears, accept it and complete the browser consent. Sync.
- Expect: big archives download via rclone.
- Prove: log shows `TIER | rclone | ...`; `rclone/rclone` binary downloaded, `rclone/rclone.conf` created, `rclone` process visible during sync. The Google consent screen says **"rclone"**, not Synchotic. (This also exercises the SHA256 pin for your platform for real.)

## Reliability gauntlet (run against each mode you ship)

Passing once is not "reliable." These are the checks that actually matter.

1. **Trust invariant, every tier (the data-loss proof).**
   - [ ] After a sync in any mode, immediately sync the same drive again. It must report **0 files to download**.
   - [ ] Then run a purge. It must delete **nothing**.
   - This proves that no matter which tier delivered the bytes, the file landed in a state the triangle blesses. `test_tier4_safety.py` asserts this on mocks; here you confirm it on real files. If a re-sync wants to re-download what you just got, STOP, that is the data-loss class of bug.

2. **Persistence across restart.**
   - [ ] After signing in (mode 2/3) or setting up rclone (mode 4), quit the app fully and reopen. You must NOT be re-prompted to authenticate.
   - BYOC note: if you come back a week later and are signed out, your GCP app is still in "Testing" status (fix: `docs/byoc.md` step 5, set publishing status to In production).

3. **Repeatability under rate limits.**
   - [ ] Run mode 4 against Rock Band twice. Some files may report "rate-limited by Google" rather than succeeding. That is expected, not a bug. Confirm the message says *rate-limited* (retry later), not *needs auth*. A second run should pick up more files.

4. **Clean cancellation.**
   - [ ] Start a mode-4 sync of a large set, hit ESC mid-download. Confirm the rclone process dies (no orphan in `ps aux | grep rclone`), and a follow-up sync resumes cleanly with no corrupted/half files left as "extra" for purge to delete.

5. **Graceful degradation with no rclone.**
   - [ ] Mode 1 (close the consent tab): blocked files fail with a clear message, everything else still syncs, the app never hangs or crashes waiting on auth.

## Known gap

There is no automated regression guarding the real network behavior of any tier. If Google changes the consent flow or the `confirm=1` / `acknowledge-abuse` interstitial (they have before), this checklist is the only tripwire. Re-run it before each release, not just once.
