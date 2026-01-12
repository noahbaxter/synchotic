# Static Sources Feature Plan

## Goal

Add support for static content sources (Guitar Hero games, Rock Band games, CSC packs) alongside the existing dynamic GDrive folder scanning.

**What we want:**
- Games section with Guitar Hero (17 archives) and Rock Band (15 folders)
- CSC packs (~32 CDN downloads)
- Existing drum drives unchanged (dynamic scanning)

**What we DON'T want:**
- Architecture rewrites
- New config systems
- Settings format changes
- Naming refactors

---

## Failed Attempt: What Went Wrong

We tried a massive refactor that touched 15 files (+1912/-419 lines) when ~200 lines would have sufficed.

### Mistakes Made

1. **Scope creep** - "Add static sources" became "rewrite config layer + settings + UI + manifest + tests"

2. **Too many changes at once** - Changed data model, settings, UI, sync logic simultaneously. Should have been 3-5 separate PRs.

3. **Naming confusion** - Introduced new vocabulary without replacing old:
   - "type" vs "category"
   - "group" vs "drive"
   - "setlist" vs "subfolder"
   - `folder_id` vs `group_id` vs `drive_id`

4. **"Legacy" code that wasn't legacy** - Created compatibility methods that became the actual API. 20+ call sites use them.

5. **No incremental testing** - Made all changes, then tried to verify. Should have: add feature → verify → refactor (if needed)

### Lessons Learned

- **One thing at a time** - Features and refactors should be separate PRs
- **Working code > clean code** - Don't break working systems for aesthetics
- **Test incrementally** - Verify each change before the next
- **If renaming, commit fully** - Either rename everywhere or don't rename

---

## The Simple Approach

### Keep What Works

The current system is fine:
- `drives.json` - list of GDrive folders to scan
- `src/config/drives.py` - DriveConfig class
- Settings with `drive_toggles` / `subfolder_toggles`
- Manifest with folder entries

### Just Add Static Sources

**Option A: Separate static_sources.json**
```json
{
  "static_sources": [
    {
      "name": "Guitar Hero",
      "category": "Games",
      "setlists": [
        {
          "name": "(2005) Guitar Hero",
          "type": "gdrive_file",
          "file_id": "1Z6tPssOVX81VVi_1XqQO9GpsNUtIhabH",
          "size": 744365116,
          "md5": "3b25d03d4316f587636b61c38f4723a2",
          "chart_count": 58,
          "file_count": 291
        }
      ]
    }
  ]
}
```

**Option B: Add to drives.json**
```json
{
  "drives": [...existing dynamic drives...],
  "static": [...static sources with full metadata...]
}
```

### Changes Needed (Minimal)

1. **manifest_gen.py** - Load static sources, add to manifest as folder entries
2. **downloader.py** - Handle `gdrive_file` and `cdn_url` source types (vs folder scanning)
3. **UI (optional)** - Group static sources under "Games" / "Community" categories

That's it. No settings changes. No config class rewrites. No renaming.

---

## Data Reference

### sources.json Contents (Preserved)

The `sources.json` file contains valuable pre-collected data:

**Guitar Hero (17 games)** - `gdrive_file` type
- File IDs, sizes, MD5 checksums, chart/file counts
- Total: ~24GB, 923 charts

**Rock Band (15 items)** - `gdrive_folder` type
- Folder IDs for each game + DLC
- Need to scan once for file metadata

**Dynamic Drives (3)** - `gdrive_folder_tree` type
- BirdmanExe, Drummer's Monthly, Misc
- Same as current drives.json

**CSC Packs (32)** - `cdn_url` type
- Direct CDN URLs, sizes, MD5s, chart/file counts
- Total: ~68GB, 5,543 charts

### Source Type Reference

| Type | Description | Example |
|------|-------------|---------|
| `gdrive_folder_tree` | Scan folder, discover subfolders | Drum drives (dynamic) |
| `gdrive_folder` | Scan folder for files | Rock Band games |
| `gdrive_file` | Download single archive | Guitar Hero games |
| `cdn_url` | Direct HTTP download | CSC packs |

---

## Implementation Plan

### Phase 1: Data Setup
- Keep `sources.json` as data reference
- Create `static_sources.json` with just the static entries (or add to drives.json)

### Phase 2: Manifest Gen
- Update `manifest_gen.py` to include static sources in output
- Static sources get folder entries like dynamic ones, but with `static: true` flag

### Phase 3: Downloader
- Add handling for `gdrive_file` downloads (single file → extract)
- Add handling for `cdn_url` downloads (HTTP GET → extract)
- Existing folder scanning unchanged

### Phase 4: UI (Optional)
- Add category headers in menu (Games, Drums, Community)
- Or just list everything flat with prefixes

### Phase 5: Verify
- Test syncing a Guitar Hero game (gdrive_file)
- Test syncing a CSC pack (cdn_url)
- Test existing drum drive (gdrive_folder_tree) still works

---

## Content Inventory

### Guitar Hero (17 games, ~24GB)

| Name | Size | Charts |
|------|------|--------|
| (2005) Guitar Hero | 744 MB | 58 |
| (2006) Guitar Hero II | 1.5 GB | 100 |
| (2007) Guitar Hero III | 1.5 GB | 75 |
| (2007) GH Encore Rocks the 80s | 627 MB | 39 |
| (2008) GH World Tour | 3.2 GB | 86 |
| (2008) GH Aerosmith | 988 MB | 47 |
| (2008) GH On Tour | 106 MB | 31 |
| (2008) GH On Tour Decades | 121 MB | 36 |
| (2009) Guitar Hero 5 | 2.8 GB | 90 |
| (2009) GH Metallica | 2.4 GB | 49 |
| (2009) GH Smash Hits | 1.9 GB | 50 |
| (2009) GH Van Halen | 1.6 GB | 47 |
| (2009) GH On Tour Modern Hits | 182 MB | 44 |
| (2009) Band Hero | 2.5 GB | 65 |
| (2009) Band Hero 2 Full Band | 177 MB | 6 |
| (2009) DJ Hero Guitar Charts | 329 MB | 10 |
| (2010) GH Warriors of Rock | 3.6 GB | 94 |

### Rock Band (15 folders)

| Name | Folder ID |
|------|-----------|
| (2007) Rock Band | 1fU-ZTbKda4T1z4nG5XLefLvkjzVRQfYL |
| (2008) Rock Band 2 | 1ffllyyoo8lfcMMCCefmx-T9eXGY1sFlB |
| (2009) Lego Rock Band | 1YIXEh4bSedxuF6jhySIWjD282nyXJwHG |
| (2009) Beatles Rock Band | 1d2T2MwyNKJ5s-PgeDuPUfcCBff5v0usg |
| (2010) Green Day Rock Band | 1cad-u4KHI4aumU35Mw15iTIjEC9nWkHS |
| (2010) Rock Band 3 | 1jgwluK968CwngGOIhg0kB37yyPT8vfe3 |
| (2012) Rock Band Blitz | 1_-VAx0V7jcK95Sc1k79EBMST8wyUSMi7 |
| (2015) Rock Band 4 | 11mUZ3NILbLFHIMPtv5GWbEgJjZmIGngQ |
| (2016) Rock Band Rivals | 1heiLMOCInvj9vqUMdUlnH7Jp0_MUe4nc |
| RB1 DLC | 1De328_NZTZKMamUc6U2cx1lg8P1ePOCi |
| RB2 DLC | 1HOUoDds2WCMNPHAX2ryE2p0L4QsZLoM8 |
| RB3 DLC | 1tRIlN13UCuNPt4je1Tjy2Qi7tB7CvQBm |
| RB4 DLC | 1ONgW-GCSsEkZF9EfhKXOMbny6V65bYh2 |
| RB ACDC Live | 1Jq8bNQjiVnnGRCuul6m34vg7IWy7UG_0 |
| RB Network | 1YsvN8SHBmTZx-mkuY1rDudF4NEDxHPED |

### CSC Packs (32 packs, ~68GB)

| Name | Size | Charts |
|------|------|--------|
| Carpal Tunnel Hero | 1.5 GB | 104 |
| Carpal Tunnel Hero 2 | 3.4 GB | 309 |
| Carpal Tunnel Hero 3 | 9.9 GB | 704 |
| Anti Hero | 3.8 GB | 402 |
| Anti Hero 2 | 4.3 GB | 365 |
| Anti Hero Beach Episode | 1.3 GB | 127 |
| Vortex Hero | 2.7 GB | 222 |
| Marathon Hero | 2.4 GB | 49 |
| Marathon Hero 2 | 6.3 GB | 152 |
| Redemption Arc | 1.0 GB | 100 |
| CHARTS | 6.0 GB | 647 |
| CHARTS 2 | 3.1 GB | 139 |
| Fall of Troy Hero | 1.5 GB | 70 |
| Circuit Breaker | 1.2 GB | 117 |
| Digitizer | 973 MB | 82 |
| Focal Point 2 | 2.2 GB | 186 |
| Zero Gravity Space Battle | 3.1 GB | 236 |
| Zero Gravity 3D | 3.7 GB | 272 |
| Symphony X Discography | 2.4 GB | 101 |
| Bitcrusher | 573 MB | 74 |
| Guitar Hero X-II | 4.0 GB | 157 |
| Max Altitude | 1.1 GB | 130 |
| S Hero | 2.8 GB | 223 |
| Code Red Vol 1 | 2.4 GB | 201 |
| Fuse Box | 3.0 GB | 255 |
| Easy Access | 669 MB | 69 |
| Post-Hardcore Hero | 637 MB | 116 |
| Attention Span | 1.3 GB | 331 |
| Guitar Grief | 1.3 GB | 122 |
| Guitar Zero 2 | 1.4 GB | 134 |
| Parallax Hero | 918 MB | 135 |
| Alhambra Discography | 1.1 GB | 49 |

### Dynamic Drives (Existing)

| Name | Folder ID |
|------|-----------|
| BirdmanExe Drive | 1OTcP60EwXnT73FYy-yjbB2C7yU6mVMTf |
| Drummer's Monthly | 1bqsJzbXRkmRda3qJFX3W36UD3Sg_eIVj |
| Misc | 1bo9XGzSa2qmvWfQRzDtLDnAzyhZnshKg |

---

## Next Steps

1. Reset all staged changes EXCEPT `sources.json`
2. Delete `src/config/sources.py` (the over-engineered config class)
3. Start fresh with Phase 1 above
