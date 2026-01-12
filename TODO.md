# Synchotic TODO

## URGENT: Static Source Architecture Issues

### Summary

Attempted to restructure manifest so static sources are grouped by collection (consistent with dynamic sources). The grouping works in the UI, but static source sync is fundamentally broken.

### What Was Done

1. **Updated `load_static_sources()` in manifest_gen.py** - Groups static sources by collection
   - Creates ONE FolderEntry per collection (e.g., "CSC Setlists", "Guitar Hero")
   - Individual sources become subfolders
   - folder_id format: `collection:{group}:{collection}`

2. **Updated manifest_gen.py incremental mode** - Now includes static sources

3. **Updated home.py** - Handles new collection folder IDs for display

4. **Updated sync.py** - `handle_toggle_collection` and `handle_configure_collection`

5. **Bumped manifest version to 3.0.0**

6. **Fixed crash in plan_downloads** - Skip files without `id` or `url`

7. **Fixed Unicode normalization in find_extra_files** - NFC vs NFD mismatch

### Current Broken Things

#### 1. Static Sources Can't Sync

Static source files have NO `id` or `url` - they're just extracted file listings:
```json
{
  "downloads": [{"url": "https://cdn.../GH1.rar", "md5": "...", "size": 1000000}],
  "files": [{"path": "GH1/song/notes.mid", "size": 123}]  // NO URL!
}
```

- `downloads` = Archives to download (has URLs)
- `files` = Extracted file listings (for validation only, no URLs)

Download planner expects files to have `id` (GDrive) or `url` (CDN). Static source files have neither → skipped.

**Result:** Guitar Hero shows "+687.6 MB" forever but never downloads.

#### 2. Static Source Purge Broken

DJ Hero should be deleted (disabled) but isn't being purged.

#### 3. Unicode Re-download Loop (Drummer's Monthly)

Files with special characters (ä, ã, ñ, é) keep re-downloading:
- "Sinistro - Pontas Soltas"
- "L'entité"
- "Näin Vastaa Autio Maa"
- "Malagueña Salerosa"

**Cause:** NFC vs NFD mismatch between manifest (NFC), macOS filesystem (NFD), and sync_state lookups (exact string match).

Partial fix in `find_extra_files`, but issue persists in plan_downloads and sync_state.

### Fix Options

**Option A: Implement Proper Static Source Downloading**
1. Download archives from `downloads` array
2. Extract to target folder
3. Validate against `files` list

**Option B: Disable Static Sources Until Fixed**
1. Skip static sources in status calculation
2. Fix purge logic
3. Document manual download requirement

**Option C: Change Static Source Format**
Regenerate static source JSONs to include archive in `files` with URL:
```json
{"files": [{"path": "GH1.rar", "url": "https://...", "md5": "..."}]}
```

### Files Modified (may need revert)

- `manifest_gen.py` - load_static_sources() grouping
- `src/manifest/manifest.py` - VERSION 3.0.0
- `src/ui/screens/home.py` - collection folder ID handling
- `src/sync/download_planner.py` - skip files without id/url
- `src/sync/extractor.py` - NFC normalization
- `sync.py` - collection handlers

### Unicode Fix Still Needed

- `src/sync/state.py` - Normalize paths in lookups
- `src/sync/download_planner.py` - Normalize paths when checking sync

---

## Feature Requests

### Pack/Drive Sharing Codes
Generate shareable "codes" that let users import the same custom list of drives. Like mod loaders for other games - share a code, friend imports it, they get the same drive setup.

Invontor suggested this would be especially useful for offshoot/niche charter drives rather than bloating the default list.

### Collapsible Category UI
Top-level categories that can be hidden/shown. Let users who only care about drums hide guitar stuff and vice versa.

Planned default structure (collapsed):
```
Drums
    BirdmanExe Drive
    Drummer's Monthly Drive
    Misc
Games (collapsed by default)
    Guitar Hero
    Rock Band
Community (collapsed by default)
    CSC (Setlists)
    Popular Charters
```

Default enabled: Only DM drives (BirdmanExe, Drummer's Monthly, Misc)

### Custom Folder Organization
Let users organize and structure their sync folders however they want. Share customs.json files around for custom setlists.

---

## Bugs / Issues

### ContentLengthError on Large Files
```
ERR: (2010) Green Day Rock Band/gdrb 21.7z - Response payload is not completed:
<ContentLengthError: 400, message='Not enough data to satisfy content length header.'>
```
Google Drive flakiness on large file downloads. Might need retry logic or resume support.

### "Gaslighting" Sync Display
Venxm reported sync showing "synced" but something seems wrong. Unclear what the actual issue is - need more info to reproduce.

### Windows Long Path Warning
Already handled with registry fix suggestion, but 4 files still skipped. Consider auto-truncating or warning more prominently.

---

## Content to Add

### Guitar Charters
Popular non-drum charters to potentially add to Community section:
- NCV
- Zantor
- TundraCH
- LemonCH
- (need more from guitar community)

### CSC Setlists
Guitar packs worth including:
- Facelift 1/2/3
- Carpal Tunnel Hero 1/2/3
- Anti Hero series
- Parallax Hero
- Alhambra Hero

---

## Won't Do / Punted

### Pause vs Cancel
hababa2 requested pause for large downloads. Pushed back because:
1. Cancel already finishes current file (effectively same as pause)
2. Google Drive doesn't handle pause/resume well for large zips
3. Only matters for one-time initial sync

### Curating Individual Charters
Decided against picking favorite charters to avoid controversy. Stick to aggregate drives (CSC, official games) as defaults. Individual charters can be added via sharing codes feature.

---

## Notes

- Planning to expand beyond DM server once things are solid
- CSC is non-controversial centralized source for guitar content
- hababa2 currently uses synchotic for guitar charts already
