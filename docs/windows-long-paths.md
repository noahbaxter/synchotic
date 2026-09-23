# Windows long paths

Windows measures a path against MAX_PATH (260 characters) and a directory
against MAX_PATH minus 12 (248, the reserve for an 8.3 name inside it). A chart
library nests drive, setlist, charter and chart, and chart folders routinely run
to 70 characters, so a perfectly ordinary library runs out of room:

```
 29  C:\CH Songs\songs\Sync Charts
 47  Misc\Drumb n' Geet Charts\SirMonkfish's FB Charts\...
 71  The Word Alive - The Only Rule Is That There Are No Rules [SirMonkfish]
 71  The Word Alive - The Only Rule Is That There Are No Rules [SirMonkfish]
```

The library root carries the extended-length prefix (`\\?\C:\...`, or
`\\?\UNC\server\share` for a share), which opts every call derived from it out
of both limits. It needs no registry key, no administrator and no reboot, and it
is applied once, in `get_library_path()`, so nothing else has to remember. See
`src/core/paths.py` and `tests/test_long_paths.py`.

Setting `LongPathsEnabled` in the registry still works and is still worth
knowing about: our executable carries the `longPathAware` manifest PyInstaller
emits, so the two halves Microsoft requires are both present. It is no longer
something a user has to be told to do.

## What only a real Windows machine can answer

Run these before shipping a release that touches path handling. Nothing here can
be faked on macOS or Linux; the string half is covered by
`tests/test_long_paths.py`, which runs anywhere.

- [ ] With `LongPathsEnabled` **off** and no reboot, sync a setlist containing a
      chart whose full path exceeds 260 characters. It should download, extract
      and appear on disk, with no `WinError 206` and no "files skipped due to
      path length" warning.
- [ ] Clone Hero scans that chart and it is playable. If it is missing, check
      `badsongs.txt` (Documents\Clone Hero) before assuming the download failed.
- [ ] Purge a drive holding one of those charts. The files must actually be
      deleted: a delete that is not prefixed cannot open the path it is
      deleting, and would leave files nothing can remove.
- [ ] Change the library to a UNC share (`\\NAS\charts`) and sync. Confirm the
      prefix used is `\\?\UNC\NAS\charts`, not `\\?\\NAS\charts`.
- [ ] Settings shows the library as `C:\...`, not `\\?\C:\...`, and the folder
      picker opens there.
- [ ] A chart with a single path component over 255 characters is still
      reported as skipped, because no prefix lifts that one.
