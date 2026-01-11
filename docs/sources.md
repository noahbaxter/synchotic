# Sources Configuration

`sources.json` is the master list of all chart sources. It uses a hierarchical structure:

```
GROUP > COLLECTION > SOURCE
```

## Source Types

| Type | Description | Example |
|------|-------------|---------|
| `url` | CDN direct download | CSC setlists |
| `file` | Google Drive single file | Guitar Hero game archives |
| `folder` | Google Drive folder (static) | Rock Band, GH Live |
| `scan` | Google Drive folder (dynamic) | Community drives |

### Static vs Dynamic

**Static** (`url`, `file`, `folder`): Pre-generated manifests in `static_sources/`. File list is known ahead of time.

**Dynamic** (`scan`): Live-scanned by `manifest_gen.py`. Folder is scanned periodically to discover new/changed files.

## Schema

```json
{
  "GROUP_NAME": {
    "COLLECTION_NAME": [
      {"name": "Display Name", "type": "url", "link": "https://..."},
      {"name": "Display Name", "type": "file", "link": "GDRIVE_ID"},
      {"name": "Display Name", "type": "folder", "link": "GDRIVE_ID"},
      {"name": "Display Name", "type": "scan", "link": "GDRIVE_ID"}
    ]
  }
}
```

## Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name shown to users |
| `type` | Yes | One of: `url`, `file`, `folder`, `scan` |
| `link` | Yes | URL or Google Drive ID |
| `description` | No | Optional description |

## Examples

```json
{"name": "(2005) Guitar Hero", "type": "file", "link": "1Z6tPss..."}
{"name": "(2007) Rock Band", "type": "folder", "link": "1fU-ZTb..."}
{"name": "Carpal Tunnel Hero", "type": "url", "link": "https://cdn.example.com/cth.rar"}
{"name": "BirdmanExe Drive", "type": "scan", "link": "1OTcP60..."}
```

## Decision Tree

```
Is the content updated frequently by multiple people?
├─ Yes → type: scan
└─ No (static)
    │
    Is it hosted on a CDN?
    ├─ Yes → type: url
    └─ No (Google Drive)
        │
        Is it a single archive file?
        ├─ Yes → type: file
        └─ No (folder of files) → type: folder
```

## Workflow

### Adding a Static Source
1. Add entry to `sources.json` with type `url`, `file`, or `folder`
2. Run `python scripts/scan_to_static.py` to generate manifest
3. Commit the generated JSON in `static_sources/`

### Adding a Dynamic Source
1. Add entry to `sources.json` with type `scan`
2. Run `python manifest_gen.py` to scan and update manifest
3. The manifest is regenerated periodically via CI
