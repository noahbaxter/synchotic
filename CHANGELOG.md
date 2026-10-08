# Changelog

Each `## x.y.z` section is published as that version's release notes. Releases fail
without one for the version in `VERSION`.

## 1.5.7
*Mostly fixes for drives and setlists getting switched on or purged when they shouldn't*

- Drives you switched off stay off: the library screen no longer turns them on and starts downloading them
- A custom folder that turns out to be a shipped setlist no longer gets its markers rewritten or purged
- Setlists are tracked per drive, so a shortcut to another drive's setlist can't steal it and download twice
- Packs that failed or never downloaded no longer get marked as synced
- Resuming a setlist import that was closed partway no longer re-downloads every pack
- Fixed Drive requests sometimes being refused as an unregistered caller
- Windows: settings now read as UTF-8, with or without a BOM, so hand-edited setlist names don't come back garbled and a Notepad-saved file doesn't wipe your choices
- Network-share libraries: markers are read in parallel, and sync shows a spinner while it checks the library
- Linux: open folder works from the AppImage launcher, and the launcher is checked and replaced more safely
- Ctrl+V and right-click paste work outside macOS
- Launcher and app write to one daily log, which now includes the toggles a sync ran with and why each file downloaded
