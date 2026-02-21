# Synchotic

Automatically download and sync Clone Hero charts from Google Drive. Pick the drives and setlists you want, hit sync, and your songs folder stays up to date — new charts download automatically, updated charts get re-downloaded, and removed setlists get cleaned up.

![Screenshot](screenshot.png)

## Getting Started

**[Download the launcher here](../../releases/tag/launcher-v1.1)**

| Platform | File |
|----------|------|
| Windows | `synchotic-launcher.exe` |
| macOS | `synchotic-launcher-macos` |

> **Step 1.** Download the launcher for your platform
>
> **Step 2.** Put it in the folder where you want your charts (e.g. your Clone Hero songs folder)
>
> **Step 3.** Double-click it

The launcher handles everything from there — it downloads the app, checks for updates, and creates a **Sync Charts** folder right next to itself.

## How to Use

1. **Enable drives** — toggle drives on or off with **Space**
2. **Pick setlists** *(optional)* — open a drive to choose individual setlists. By default all setlists are included.
3. **Sync** — press **S** to download everything you've enabled

Your charts appear in the **Sync Charts** folder next to the launcher. Every time you run it again, it checks for new or updated charts and syncs automatically.

You can also add your own Google Drive folders, sign in to Google for faster downloads, and more — the controls are shown at the bottom of the screen.

## Troubleshooting

### What happens when I disable a setlist?

It gets removed from disk on the next sync. You can always re-enable it and sync again to re-download it.

### Where are my charts?

In the **Sync Charts** folder, right next to where you put the launcher.

### Where are logs?

In `.dm-sync/logs/` next to the launcher. Each day gets its own log file.

### Downloads fail with path errors (Windows)

Windows blocks paths over 260 characters. To fix:

1. Open **Registry Editor** (search for `regedit` in the Start menu)
2. Go to `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem`
3. Set `LongPathsEnabled` to `1`
4. Restart your computer

### macOS: security warning when opening

This shouldn't happen with signed builds, but if it does: right-click the file, click **Open**, then click **Open** again in the confirmation dialog. You only need to do this once.

---

<details>
<summary><strong>Linux</strong></summary>

There's no pre-built binary for Linux, but it's just a Python script:

```bash
git clone https://github.com/noahbaxter/synchotic.git
cd synchotic
pip install -r requirements.txt
python sync.py
```

For .rar archive extraction, you'll also need `unrar` installed (`sudo apt install unrar` or equivalent).

</details>

<details>
<summary><strong>For Developers</strong></summary>

### Running from Source

```bash
pip install -r requirements.txt
python sync.py
```

### Building

Builds are automatic via GitHub Actions on push to `main`. To build locally:

```bash
./build.sh                       # Build app only
./build.sh launcher              # Build launcher only
./build.sh dev ~/Desktop/test    # Build both and copy to a test folder
```

### Local Testing

After `build.sh dev`, run the launcher from the target folder:

```bash
./synchotic-launcher-macos --dev           # Replace app, keep settings
./synchotic-launcher-macos --dev --clean   # Fresh install (nuke .dm-sync)
```

`--dev` uses a local `app-macos.zip` if present, otherwise the existing `_app` folder. `--clean` nukes `.dm-sync/` first.

</details>
