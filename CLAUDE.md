# Synchotic

Google Drive sync tool for music game (Clone Hero) setlists. Python CLI with TUI.

## Testing

Run `pytest tests/ -v` before committing changes to `src/sync/` — especially status.py, download_planner.py, purge_planner.py (the "triangle"). These three disagree constantly and have caused data loss before.

No purge-related changes without manual verification. Cache invalidation changes need manual toggle-during-scan testing.
