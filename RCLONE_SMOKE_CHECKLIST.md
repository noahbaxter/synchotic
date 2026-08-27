# rclone tier: manual smoke checklist (release gate)

These cannot be automated (need real Google auth + each OS). Run before release. The SHA256 pins in `src/core/constants.py` are already filled and verified against the official v1.69.1 SHA256SUMS (2026-06-13).

## 1. THE load-bearing check: copyid + drive.readonly + acknowledge-abuse on a real flagged file

The whole tier depends on this combination working (the plan flagged it as not explicitly documented). A "flagged" file is a large archive that triggers Google's virus-scan interstitial (anonymous download returns HTML). Pick one the measurement found, e.g. a >100MB archive from the Misc or Rock Band drive.

```bash
RC=rclone   # or the managed binary at ~/.dm-sync/rclone/rclone
$RC --config /tmp/sc.conf config create synchotic drive scope=drive.readonly config_is_local=true
# ^ browser opens, click consent. Then:
$RC --config /tmp/sc.conf backend copyid synchotic: <FLAGGED_FILE_ID> /tmp/out/ --drive-acknowledge-abuse
ls -la /tmp/out/
```
PASS = the flagged file downloads intact. FAIL = STOP, the tier's premise is broken; revisit before shipping.

## 2. Consent flow, each OS
- [ ] macOS: first sync with blocked files shows the explainer, browser opens, consent sticks, sync proceeds.
- [ ] Windows: same. Confirm the freshly downloaded `rclone.exe` is not quarantined by Defender/SmartScreen (the binary is unsigned). If quarantined, note remediation (the managed-binary fallback or BYOC).
- [ ] Linux: same.

## 3. Daemon lifecycle
- [ ] rcd spawns on a random localhost port, dies on sync end and on ESC mid-sync.
- [ ] Windows: confirm spawn/kill works (note: `reap_stale` uses `ps`, which is POSIX-only; on Windows a stale daemon from a crash is not reaped, only the current one is stopped normally. Acceptable, but verify no orphan rclone.exe lingers after a normal run).

## 4. Throughput tuning
- [ ] Run a sync of the Rock Band set (worst case: many 10-100MB blocked archives). Compare wall-clock to the OAuth path. Tune `--transfers` (currently rclone default) via rc `core/stats` if needed. Expectation: comparable for big files, <=2-3x slower on Rock Band, nowhere near 10x.

## 5. Trust invariant in the real app
- [ ] After a real rclone-tier sync, run a second sync: it should report everything synced (0 to download), and a purge dry-run should delete nothing. This is the automated `test_tier4_safety.py` invariant, confirmed against the real app.
