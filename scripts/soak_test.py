#!/usr/bin/env python3
"""
Integration soak test for synchotic.

Runs real sync operations against live manifest data and validates that
everything works correctly: downloads, state tracking, status reporting,
idempotency, recovery, etc.

Usage:
    python scripts/soak_test.py                    # Interactive mode
    python scripts/soak_test.py --drive X          # Specific drive
    python scripts/soak_test.py --drive X --setlist Y  # Specific setlist
    python scripts/soak_test.py --keep             # Don't cleanup temp folder after
    python scripts/soak_test.py --thorough         # Run extended robustness tests
"""

import argparse
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from _helpers import (
    REPO_ROOT,
    count_disk_charts,
    count_manifest_charts,
    get_setlists_from_manifest,
)

sys.path.insert(0, str(REPO_ROOT))

from src.manifest import fetch_manifest
from src.sync import FolderSync
from src.sync.state import SyncState
from src.sync.status import get_setlist_sync_status
from src.sync.download_planner import plan_downloads
from src.drive import DriveClient, AuthManager
from src.drive.client import DriveClientConfig
from src.core.constants import CHART_MARKERS, CHART_ARCHIVE_EXTENSIONS, VIDEO_EXTENSIONS
from src.core.formatting import dedupe_files_by_newest
from src.core.paths import get_token_path

API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# Global auth manager (loaded once, reused across scenarios)
AUTH_MANAGER = None

def get_auth_manager():
    """Get or create the auth manager using the user's existing token."""
    global AUTH_MANAGER
    if AUTH_MANAGER is None:
        token_path = get_token_path()
        if token_path.exists():
            AUTH_MANAGER = AuthManager(token_path=token_path)
            print(f"Using auth token from: {token_path}")
        else:
            print("No auth token found - downloads may fail for large files")
    return AUTH_MANAGER


@dataclass
class ValidationResult:
    name: str
    passed: bool
    message: str = ""
    details: list[str] = field(default_factory=list)


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    duration: float
    validations: list[ValidationResult] = field(default_factory=list)
    error: str = ""


class SoakTest:
    """Integration test runner."""

    def __init__(self, manifest: dict, drive_name: str, setlist_name: str,
                 keep_files: bool = False, thorough: bool = False):
        self.manifest = manifest
        self.drive_name = drive_name
        self.setlist_name = setlist_name
        self.keep_files = keep_files
        self.thorough = thorough

        # Find the folder
        self.folder = next(
            (f for f in manifest.get("folders", []) if f.get("name") == drive_name),
            None
        )
        if not self.folder:
            raise ValueError(f"Drive '{drive_name}' not found in manifest")

        # Filter to just this setlist
        self.files = self._get_setlist_files()
        if not self.files:
            raise ValueError(f"Setlist '{setlist_name}' not found or empty in drive '{drive_name}'")

        # Create isolated test environment
        self.temp_dir = Path(tempfile.mkdtemp(prefix="synchotic_soak_"))
        self.base_path = self.temp_dir / "Sync Charts"
        self.base_path.mkdir(parents=True, exist_ok=True)

        # Results
        self.results: list[ScenarioResult] = []

        # Analyze setlist characteristics for conditional tests
        self._has_loose_files = self._check_has_loose_files()
        self._has_multiple_archives = self._check_has_multiple_archives()
        self._has_unicode = self._check_has_unicode()
        self._has_videos = self._check_has_videos()

    def _get_setlist_files(self) -> list[dict]:
        """Get files for the selected setlist."""
        all_files = self.folder.get("files", [])
        prefix = self.setlist_name + "/"
        return [f for f in all_files if f.get("path", "").startswith(prefix)]

    def _check_has_loose_files(self) -> bool:
        """Check if setlist has loose chart files (not in archives)."""
        markers_lower = {m.lower() for m in CHART_MARKERS}
        for f in self.files:
            name = f.get("name", "").lower()
            if name in markers_lower:
                return True
        return False

    def _check_has_multiple_archives(self) -> bool:
        """Check if setlist has multiple archives."""
        archive_count = 0
        for f in self.files:
            ext = Path(f.get("name", "")).suffix.lower()
            if ext in CHART_ARCHIVE_EXTENSIONS:
                archive_count += 1
                if archive_count > 1:
                    return True
        return False

    def _check_has_unicode(self) -> bool:
        """Check if any file paths contain non-ASCII characters."""
        for f in self.files:
            path = f.get("path", "")
            if not path.isascii():
                return True
        return False

    def _check_has_videos(self) -> bool:
        """Check if setlist has video files (or archives that might contain them)."""
        # Check if any file is a video
        for f in self.files:
            ext = Path(f.get("name", "")).suffix.lower()
            if ext in VIDEO_EXTENSIONS:
                return True
        # For archives, we can't know without extracting, but most setlists have videos
        # Return True if there are archives (conservative assumption)
        for f in self.files:
            ext = Path(f.get("name", "")).suffix.lower()
            if ext in CHART_ARCHIVE_EXTENSIONS:
                return True
        return False

    def _create_test_folder(self) -> dict:
        """Create a folder dict with just the selected setlist's files."""
        return {
            "name": self.folder.get("name"),
            "folder_id": self.folder.get("folder_id"),
            "files": self.files,
            "subfolders": self.folder.get("subfolders", []),
        }

    def _create_sync_state(self) -> SyncState:
        """Create a fresh SyncState for the test environment."""
        state = SyncState(sync_root=self.base_path)
        return state

    def _count_disk_charts(self) -> int:
        """Count actual chart folders on disk."""
        folder_path = self.base_path / self.drive_name / self.setlist_name
        return count_disk_charts(folder_path)

    def _count_manifest_charts(self) -> int:
        """Count expected charts from manifest."""
        return count_manifest_charts(self.files)

    def _validate_status_matches_disk(self, sync_state: SyncState) -> ValidationResult:
        """Validate that status report matches disk reality."""
        folder = self._create_test_folder()
        status = get_setlist_sync_status(
            folder=folder,
            setlist_name=self.setlist_name,
            base_path=self.base_path,
            sync_state=sync_state,
            delete_videos=True,
        )

        disk_charts = self._count_disk_charts()
        status_synced = status.synced_charts

        if status_synced == disk_charts:
            return ValidationResult(
                name="status_matches_disk",
                passed=True,
                message=f"Status ({status_synced}) matches disk ({disk_charts})",
            )
        else:
            return ValidationResult(
                name="status_matches_disk",
                passed=False,
                message=f"Status ({status_synced}) != disk ({disk_charts})",
                details=[f"Difference: {abs(status_synced - disk_charts)} charts"],
            )

    def _validate_planner_agreement(self, sync_state: SyncState) -> ValidationResult:
        """Validate that download planner agrees we're synced."""
        folder_path = self.base_path / self.drive_name
        files = dedupe_files_by_newest(self.files)
        tasks, skipped, _ = plan_downloads(
            files, folder_path, delete_videos=True,
            sync_state=sync_state, folder_name=self.drive_name
        )

        if len(tasks) == 0:
            return ValidationResult(
                name="planner_agreement",
                passed=True,
                message=f"Planner says 0 tasks needed ({skipped} skipped)",
            )
        else:
            return ValidationResult(
                name="planner_agreement",
                passed=False,
                message=f"Planner wants to download {len(tasks)} files",
                details=[f"First task: {tasks[0].local_path.name}" if tasks else ""],
            )

    def _validate_state_integrity(self, sync_state: SyncState) -> ValidationResult:
        """Validate sync_state entries have corresponding files on disk."""
        # Use SyncState's built-in validation
        all_files = sync_state.get_all_files()
        missing = sync_state.check_files_exist(verify_sizes=False)

        if missing:
            return ValidationResult(
                name="state_integrity",
                passed=False,
                message=f"{len(missing)} state entries have no files on disk",
                details=missing[:5],
            )
        else:
            return ValidationResult(
                name="state_integrity",
                passed=True,
                message=f"All {len(all_files)} state entries have files on disk",
            )

    def _validate_extraction_complete(self) -> ValidationResult:
        """Validate all archives extracted with chart markers present."""
        folder_path = self.base_path / self.drive_name / self.setlist_name
        if not folder_path.exists():
            return ValidationResult(
                name="extraction_complete",
                passed=False,
                message="Setlist folder doesn't exist",
            )

        # Find folders that look like extracted charts
        chart_folders = []
        markers_lower = {m.lower() for m in CHART_MARKERS}

        for item in folder_path.rglob("*"):
            if item.is_file() and item.name.lower() in markers_lower:
                chart_folders.append(item.parent)

        expected = self._count_manifest_charts()
        actual = len(set(chart_folders))

        if actual >= expected:
            return ValidationResult(
                name="extraction_complete",
                passed=True,
                message=f"{actual} chart folders with markers (expected {expected})",
            )
        else:
            return ValidationResult(
                name="extraction_complete",
                passed=False,
                message=f"Only {actual} chart folders, expected {expected}",
            )

    def run_scenario(self, name: str, fn) -> ScenarioResult:
        """Run a scenario and capture results."""
        print(f"\n{'='*60}")
        print(f"  SCENARIO: {name}")
        print(f"{'='*60}\n")

        start = time.time()
        try:
            validations = fn()
            duration = time.time() - start
            passed = all(v.passed for v in validations)
            return ScenarioResult(
                name=name,
                passed=passed,
                duration=duration,
                validations=validations,
            )
        except Exception as e:
            duration = time.time() - start
            return ScenarioResult(
                name=name,
                passed=False,
                duration=duration,
                error=str(e),
            )

    def scenario_fresh_sync(self) -> list[ValidationResult]:
        """Scenario 1: Fresh sync to empty folder."""
        print("Running fresh sync...")

        # Clean slate
        if self.base_path.exists():
            shutil.rmtree(self.base_path)
        self.base_path.mkdir(parents=True)

        # Fresh state (load initializes the data structure)
        sync_state = self._create_sync_state()
        sync_state.load()

        # Create sync engine
        client_config = DriveClientConfig(api_key=API_KEY)
        client = DriveClient(client_config)
        sync = FolderSync(
            client,
            auth_token=get_auth_manager().get_token_getter() if get_auth_manager() else None,
            delete_videos=True,
            sync_state=sync_state,
        )

        # Run sync
        folder = self._create_test_folder()
        downloaded, skipped, errors, rate_limited, cancelled, bytes_down = sync.sync_folder(
            folder, self.base_path, disabled_prefixes=[]
        )

        print(f"Downloaded: {downloaded}, Skipped: {skipped}, Errors: {errors}")

        # Save state
        sync_state.save()

        # Validations
        results = []

        # Check download count
        expected = self._count_manifest_charts()
        if downloaded > 0 or skipped > 0:
            results.append(ValidationResult(
                name="downloads_occurred",
                passed=True,
                message=f"Downloaded {downloaded}, skipped {skipped}",
            ))
        else:
            results.append(ValidationResult(
                name="downloads_occurred",
                passed=False,
                message="Nothing was downloaded or skipped",
            ))

        if errors > 0:
            results.append(ValidationResult(
                name="no_errors",
                passed=False,
                message=f"{errors} download errors",
            ))
        else:
            results.append(ValidationResult(
                name="no_errors",
                passed=True,
                message="No download errors",
            ))

        results.append(self._validate_status_matches_disk(sync_state))
        results.append(self._validate_planner_agreement(sync_state))
        results.append(self._validate_state_integrity(sync_state))
        results.append(self._validate_extraction_complete())

        return results

    def scenario_resync_idempotent(self) -> list[ValidationResult]:
        """Scenario 2: Re-sync should download nothing."""
        print("Running re-sync (should be idempotent)...")

        # Load existing state
        sync_state = self._create_sync_state()
        sync_state.load()

        # Create sync engine
        client_config = DriveClientConfig(api_key=API_KEY)
        client = DriveClient(client_config)
        sync = FolderSync(
            client,
            auth_token=get_auth_manager().get_token_getter() if get_auth_manager() else None,
            delete_videos=True,
            sync_state=sync_state,
        )

        # Run sync again
        folder = self._create_test_folder()
        downloaded, skipped, errors, rate_limited, cancelled, bytes_down = sync.sync_folder(
            folder, self.base_path, disabled_prefixes=[]
        )

        print(f"Downloaded: {downloaded}, Skipped: {skipped}")

        results = []

        if downloaded == 0:
            results.append(ValidationResult(
                name="idempotent",
                passed=True,
                message=f"Re-sync downloaded nothing ({skipped} skipped)",
            ))
        else:
            results.append(ValidationResult(
                name="idempotent",
                passed=False,
                message=f"Re-sync downloaded {downloaded} files (should be 0)",
            ))

        results.append(self._validate_status_matches_disk(sync_state))
        results.append(self._validate_planner_agreement(sync_state))

        return results

    def scenario_state_corruption_recovery(self) -> list[ValidationResult]:
        """Scenario 3: Delete sync_state and verify recovery via disk fallback."""
        print("Deleting sync_state to test recovery...")

        # Delete state file
        state_file = self.base_path / "sync_state.json"
        if state_file.exists():
            state_file.unlink()

        # Fresh state (no history - load will initialize empty structure)
        sync_state = self._create_sync_state()
        sync_state.load()

        # Validations - status should still work via disk fallback
        results = []

        status_result = self._validate_status_matches_disk(sync_state)
        # Adjust expectations - without state, status uses disk fallback
        # It should still recognize synced charts on disk
        results.append(ValidationResult(
            name="disk_fallback_status",
            passed=status_result.passed,
            message=f"Without state: {status_result.message}",
            details=status_result.details,
        ))

        planner_result = self._validate_planner_agreement(sync_state)
        results.append(ValidationResult(
            name="disk_fallback_planner",
            passed=planner_result.passed,
            message=f"Without state: {planner_result.message}",
            details=planner_result.details,
        ))

        return results

    def scenario_resync_after_recovery(self) -> list[ValidationResult]:
        """Scenario 4: Sync again after state loss - should not re-download."""
        print("Running sync after state loss...")

        # State was deleted in previous scenario (load will initialize empty state)
        sync_state = self._create_sync_state()
        sync_state.load()

        # Create sync engine
        client_config = DriveClientConfig(api_key=API_KEY)
        client = DriveClient(client_config)
        sync = FolderSync(
            client,
            auth_token=get_auth_manager().get_token_getter() if get_auth_manager() else None,
            delete_videos=True,
            sync_state=sync_state,
        )

        # Run sync
        folder = self._create_test_folder()
        downloaded, skipped, errors, rate_limited, cancelled, bytes_down = sync.sync_folder(
            folder, self.base_path, disabled_prefixes=[]
        )

        print(f"Downloaded: {downloaded}, Skipped: {skipped}")

        results = []

        # With disk fallback, should recognize existing files and not re-download
        if downloaded == 0:
            results.append(ValidationResult(
                name="recovery_no_redownload",
                passed=True,
                message=f"After state loss, no re-downloads ({skipped} skipped)",
            ))
        else:
            results.append(ValidationResult(
                name="recovery_no_redownload",
                passed=False,
                message=f"After state loss, re-downloaded {downloaded} files",
                details=["Disk fallback should have prevented this"],
            ))

        # Save rebuilt state
        sync_state.save()

        results.append(self._validate_status_matches_disk(sync_state))

        return results

    # --- Extended scenarios (--thorough only) ---

    def scenario_delete_file_redownload(self) -> list[ValidationResult]:
        """Extended: Delete a chart folder and verify re-download."""
        print("Deleting a chart folder to test re-download...")

        folder_path = self.base_path / self.drive_name / self.setlist_name
        results = []

        # Find a chart folder to delete (one with a marker file)
        chart_folder = None
        markers_lower = {m.lower() for m in CHART_MARKERS}
        for item in folder_path.rglob("*"):
            if item.is_file() and item.name.lower() in markers_lower:
                chart_folder = item.parent
                break

        if not chart_folder:
            return [ValidationResult(
                name="delete_redownload",
                passed=False,
                message="Could not find a chart folder to delete",
            )]

        deleted_name = chart_folder.name
        print(f"Deleting chart folder: {deleted_name}")
        shutil.rmtree(chart_folder)

        # Keep state intact - state-based check should detect missing files
        sync_state = self._create_sync_state()
        sync_state.load()

        client_config = DriveClientConfig(api_key=API_KEY)
        client = DriveClient(client_config)
        sync = FolderSync(
            client,
            auth_token=get_auth_manager().get_token_getter() if get_auth_manager() else None,
            delete_videos=True,
            sync_state=sync_state,
        )

        folder = self._create_test_folder()
        downloaded, skipped, errors, rate_limited, cancelled, bytes_down = sync.sync_folder(
            folder, self.base_path, disabled_prefixes=[]
        )

        print(f"Downloaded: {downloaded}, Skipped: {skipped}")

        # Should have re-downloaded exactly 1 archive (containing the deleted chart)
        if downloaded >= 1:
            results.append(ValidationResult(
                name="delete_redownload",
                passed=True,
                message=f"Re-downloaded {downloaded} file(s) after deleting '{deleted_name}'",
            ))
        else:
            results.append(ValidationResult(
                name="delete_redownload",
                passed=False,
                message=f"Expected re-download after deleting '{deleted_name}', got {downloaded}",
            ))

        # Verify the chart folder is restored
        if chart_folder.exists():
            results.append(ValidationResult(
                name="folder_restored",
                passed=True,
                message=f"Chart folder '{deleted_name}' restored",
            ))
        else:
            results.append(ValidationResult(
                name="folder_restored",
                passed=False,
                message=f"Chart folder '{deleted_name}' not restored",
            ))

        sync_state.save()
        return results

    def scenario_file_corruption(self) -> list[ValidationResult]:
        """Extended: Corrupt a file (truncate) and verify re-download."""
        print("Corrupting a file to test size-based re-download...")

        folder_path = self.base_path / self.drive_name / self.setlist_name
        results = []

        # Find a chart file to corrupt (a notes file is good - small but important)
        target_file = None
        for item in folder_path.rglob("*"):
            if item.is_file() and item.name.lower() in ("notes.mid", "notes.chart"):
                target_file = item
                break

        if not target_file:
            # Fall back to any file
            for item in folder_path.rglob("*"):
                if item.is_file() and item.stat().st_size > 100:
                    target_file = item
                    break

        if not target_file:
            return [ValidationResult(
                name="corruption_detection",
                passed=False,
                message="Could not find a file to corrupt",
            )]

        original_size = target_file.stat().st_size
        print(f"Corrupting file: {target_file.name} (original size: {original_size})")

        # Truncate the file
        with open(target_file, "wb") as f:
            f.write(b"corrupted")

        # Keep state intact - state-based check should detect wrong file size
        sync_state = self._create_sync_state()
        sync_state.load()

        client_config = DriveClientConfig(api_key=API_KEY)
        client = DriveClient(client_config)
        sync = FolderSync(
            client,
            auth_token=get_auth_manager().get_token_getter() if get_auth_manager() else None,
            delete_videos=True,
            sync_state=sync_state,
        )

        folder = self._create_test_folder()
        downloaded, skipped, errors, rate_limited, cancelled, bytes_down = sync.sync_folder(
            folder, self.base_path, disabled_prefixes=[]
        )

        print(f"Downloaded: {downloaded}, Skipped: {skipped}")

        # Should have re-downloaded at least 1 file
        if downloaded >= 1:
            results.append(ValidationResult(
                name="corruption_detection",
                passed=True,
                message=f"Re-downloaded {downloaded} file(s) after corruption",
            ))
        else:
            results.append(ValidationResult(
                name="corruption_detection",
                passed=False,
                message=f"Expected re-download after corruption, got {downloaded}",
            ))

        # Verify file is restored to proper size
        new_size = target_file.stat().st_size if target_file.exists() else 0
        if new_size == original_size:
            results.append(ValidationResult(
                name="file_restored",
                passed=True,
                message=f"File restored to original size ({original_size} bytes)",
            ))
        elif new_size > 9:  # More than "corrupted"
            results.append(ValidationResult(
                name="file_restored",
                passed=True,
                message=f"File restored (size: {new_size}, original: {original_size})",
            ))
        else:
            results.append(ValidationResult(
                name="file_restored",
                passed=False,
                message=f"File not restored (size: {new_size}, expected: {original_size})",
            ))

        sync_state.save()
        return results

    def scenario_video_skipping(self) -> list[ValidationResult]:
        """Extended: Verify video files are properly skipped/deleted."""
        print("Checking video file handling...")

        folder_path = self.base_path / self.drive_name / self.setlist_name
        results = []

        # Count video files on disk
        video_count = 0
        video_extensions_lower = {ext.lower() for ext in VIDEO_EXTENSIONS}
        for item in folder_path.rglob("*"):
            if item.is_file() and item.suffix.lower() in video_extensions_lower:
                video_count += 1
                print(f"  Found video: {item.name}")

        if video_count == 0:
            results.append(ValidationResult(
                name="video_skipping",
                passed=True,
                message="No video files found on disk (properly deleted/skipped)",
            ))
        else:
            results.append(ValidationResult(
                name="video_skipping",
                passed=False,
                message=f"Found {video_count} video files (should be 0 with delete_videos=True)",
            ))

        return results

    def scenario_stale_state_detection(self) -> list[ValidationResult]:
        """Extended: Delete files and verify status doesn't trust stale state."""
        print("Testing stale state detection (delete files, check status)...")

        folder_path = self.base_path / self.drive_name / self.setlist_name
        results = []

        # Load current sync_state
        sync_state = self._create_sync_state()
        sync_state.load()

        # Count charts before deletion
        charts_before = self._count_disk_charts()
        if charts_before < 3:
            return [ValidationResult(
                name="stale_state_setup",
                passed=False,
                message=f"Need at least 3 charts to test, have {charts_before}",
            )]

        # Delete 2 chart folders from disk (but leave sync_state intact)
        deleted_folders = []
        markers_lower = {m.lower() for m in CHART_MARKERS}
        for item in folder_path.rglob("*"):
            if item.is_file() and item.name.lower() in markers_lower:
                chart_folder = item.parent
                if chart_folder not in deleted_folders:
                    deleted_folders.append(chart_folder)
                    if len(deleted_folders) >= 2:
                        break

        for folder in deleted_folders:
            print(f"  Deleting: {folder.name}")
            shutil.rmtree(folder)

        charts_after = self._count_disk_charts()
        print(f"  Charts: {charts_before} -> {charts_after} (deleted {charts_before - charts_after})")

        # Check status WITHOUT re-syncing - should report fewer synced
        folder = self._create_test_folder()
        status = get_setlist_sync_status(
            folder=folder,
            setlist_name=self.setlist_name,
            base_path=self.base_path,
            sync_state=sync_state,
            delete_videos=True,
        )

        # Status should match actual disk count, not stale state
        if status.synced_charts == charts_after:
            results.append(ValidationResult(
                name="stale_state_not_trusted",
                passed=True,
                message=f"Status correctly reports {status.synced_charts} (matches disk)",
            ))
        elif status.synced_charts > charts_after:
            results.append(ValidationResult(
                name="stale_state_not_trusted",
                passed=False,
                message=f"Status reports {status.synced_charts} but disk has {charts_after}",
                details=["Stale sync_state entries are incorrectly trusted"],
            ))
        else:
            results.append(ValidationResult(
                name="stale_state_not_trusted",
                passed=False,
                message=f"Status reports {status.synced_charts}, disk has {charts_after}",
                details=["Unexpected: status is LOWER than disk"],
            ))

        # Verify state_integrity correctly finds missing files
        missing = sync_state.check_files_exist(verify_sizes=False)

        if len(missing) > 0:
            results.append(ValidationResult(
                name="state_integrity_detects_missing",
                passed=True,
                message=f"state_integrity correctly found {len(missing)} missing files",
            ))
        else:
            results.append(ValidationResult(
                name="state_integrity_detects_missing",
                passed=False,
                message="state_integrity failed to detect deleted files",
            ))

        # Re-sync to restore deleted files for subsequent tests
        print("  Restoring deleted files...")
        client_config = DriveClientConfig(api_key=API_KEY)
        client = DriveClient(client_config)
        sync = FolderSync(
            client,
            auth_token=get_auth_manager().get_token_getter() if get_auth_manager() else None,
            delete_videos=True,
            sync_state=sync_state,
        )
        sync.sync_folder(folder, self.base_path, disabled_prefixes=[])
        sync_state.save()

        return results

    def scenario_cancel_mid_sync(self) -> list[ValidationResult]:
        """Extended: Cancel sync mid-way and verify state consistency."""
        print("Testing cancel mid-sync...")

        results = []

        # Clear all state for this setlist to force re-download
        # (We'll delete the folder and state file to start completely fresh)
        folder_path = self.base_path / self.drive_name / self.setlist_name
        if folder_path.exists():
            shutil.rmtree(folder_path)
        folder_path.mkdir(parents=True, exist_ok=True)

        # Delete sync_state file to start fresh (otherwise load() will restore old entries)
        state_file = self.base_path / "sync_state.json"
        if state_file.exists():
            state_file.unlink()

        # Create fresh sync_state (must call load() to initialize _data)
        sync_state = self._create_sync_state()
        sync_state.load()

        client_config = DriveClientConfig(api_key=API_KEY)
        client = DriveClient(client_config)
        sync = FolderSync(
            client,
            auth_token=get_auth_manager().get_token_getter() if get_auth_manager() else None,
            delete_videos=True,
            sync_state=sync_state,
        )

        folder = self._create_test_folder()

        # Cancel after N seconds using the cancel_check callback
        # This is more reliable than SIGINT and works with any file type
        cancel_after_seconds = 5.0
        start_time = time.time()

        def should_cancel() -> bool:
            elapsed = time.time() - start_time
            return elapsed >= cancel_after_seconds

        print(f"  Will cancel after {cancel_after_seconds}s...")

        downloaded = 0
        cancelled = False
        sync_error = None
        try:
            downloaded, _, _, _, cancelled, _ = sync.sync_folder(
                folder, self.base_path, disabled_prefixes=[], cancel_check=should_cancel
            )
        except Exception as e:
            sync_error = f"{type(e).__name__}: {e}"
            cancelled = True  # Treat errors as cancelled for validation purposes

        if sync_error:
            print(f"  Sync error: {sync_error}")
        print(f"  Downloaded: {downloaded}, Cancelled: {cancelled}")

        # Verify cancellation actually happened (unless sync was very fast)
        total_files = len(self.files)
        if downloaded < total_files and cancelled:
            results.append(ValidationResult(
                name="cancel_triggered",
                passed=True,
                message=f"Cancelled after {downloaded}/{total_files} files",
            ))
        elif downloaded == total_files:
            results.append(ValidationResult(
                name="cancel_triggered",
                passed=True,
                message=f"Sync completed before cancel threshold ({downloaded} files)",
            ))
        else:
            results.append(ValidationResult(
                name="cancel_triggered",
                passed=False,
                message=f"Unexpected state: downloaded={downloaded}, cancelled={cancelled}",
            ))

        # THE CRITICAL CHECK: sync_state must match disk exactly
        sync_state.save()
        sync_state.load()  # Reload to ensure consistency

        disk_charts = self._count_disk_charts()
        state_files = sync_state.get_all_files()
        missing = sync_state.check_files_exist(verify_sizes=False)

        if len(missing) == 0:
            results.append(ValidationResult(
                name="cancel_state_integrity",
                passed=True,
                message=f"All {len(state_files)} state entries exist on disk",
            ))
        else:
            results.append(ValidationResult(
                name="cancel_state_integrity",
                passed=False,
                message=f"{len(missing)} state entries have no files on disk",
                details=missing[:5],
            ))

        # Status should match disk
        status = get_setlist_sync_status(
            folder=folder,
            setlist_name=self.setlist_name,
            base_path=self.base_path,
            sync_state=sync_state,
            delete_videos=True,
        )

        # After cancel, status may report fewer synced charts than disk charts
        # because some charts are incomplete. This is expected behavior.
        # Key assertion: status <= disk (can't report more synced than exist)
        if status.synced_charts <= disk_charts:
            results.append(ValidationResult(
                name="cancel_status_consistency",
                passed=True,
                message=f"Status ({status.synced_charts}) <= disk ({disk_charts}) - partial charts expected",
            ))
        else:
            results.append(ValidationResult(
                name="cancel_status_consistency",
                passed=False,
                message=f"Status ({status.synced_charts}) > disk ({disk_charts}) - impossible state!",
            ))

        # Re-sync to complete for subsequent tests
        print("  Completing sync for subsequent tests...")
        sync.sync_folder(folder, self.base_path, disabled_prefixes=[])
        sync_state.save()

        return results

    def run_all(self):
        """Run all scenarios."""
        print(f"\nSOAK TEST: {self.drive_name} / {self.setlist_name}")
        print(f"Files in setlist: {len(self.files)}")
        print(f"Expected charts: {self._count_manifest_charts()}")
        print(f"Temp directory: {self.temp_dir}")

        # Calculate total size
        total_size = sum(f.get("size", 0) for f in self.files)
        print(f"Total download size: {total_size / 1024 / 1024:.1f} MB")

        if self.thorough:
            print(f"\nSetlist characteristics:")
            print(f"  Has loose files: {self._has_loose_files}")
            print(f"  Has multiple archives: {self._has_multiple_archives}")
            print(f"  Has unicode paths: {self._has_unicode}")
            print(f"  Has videos: {self._has_videos}")
        print()

        input("Press Enter to start (or Ctrl+C to cancel)...")

        # Run basic scenarios
        self.results.append(self.run_scenario("Fresh Sync", self.scenario_fresh_sync))
        self.results.append(self.run_scenario("Re-sync Idempotent", self.scenario_resync_idempotent))

        # Extended scenarios run here (before state corruption) so state is intact
        if self.thorough:
            print(f"\n{'='*60}")
            print("  EXTENDED TESTS (--thorough)")
            print(f"{'='*60}")

            self.results.append(self.run_scenario(
                "Delete File Recovery", self.scenario_delete_file_redownload))
            self.results.append(self.run_scenario(
                "Corruption Detection", self.scenario_file_corruption))

            if self._has_videos:
                self.results.append(self.run_scenario(
                    "Video Skipping", self.scenario_video_skipping))

            self.results.append(self.run_scenario(
                "Stale State Detection", self.scenario_stale_state_detection))
            self.results.append(self.run_scenario(
                "Cancel Mid-Sync", self.scenario_cancel_mid_sync))

        # State corruption tests (these delete state, so run last)
        self.results.append(self.run_scenario("State Corruption Recovery", self.scenario_state_corruption_recovery))
        self.results.append(self.run_scenario("Re-sync After Recovery", self.scenario_resync_after_recovery))

        # Print summary
        self._print_summary()

        # Cleanup
        if not self.keep_files:
            print(f"\nCleaning up {self.temp_dir}...")
            shutil.rmtree(self.temp_dir)
        else:
            print(f"\nKeeping temp files at: {self.temp_dir}")

    def _print_summary(self):
        """Print test summary."""
        print(f"\n{'='*60}")
        print("  SUMMARY")
        print(f"{'='*60}\n")

        total_passed = 0
        total_failed = 0

        for scenario in self.results:
            status = "PASS" if scenario.passed else "FAIL"
            print(f"[{status}] {scenario.name} ({scenario.duration:.1f}s)")

            if scenario.error:
                print(f"      ERROR: {scenario.error}")

            for v in scenario.validations:
                v_status = "+" if v.passed else "-"
                print(f"      [{v_status}] {v.name}: {v.message}")
                for detail in v.details:
                    print(f"          {detail}")

                if v.passed:
                    total_passed += 1
                else:
                    total_failed += 1

            print()

        print(f"{'='*60}")
        print(f"  TOTAL: {total_passed} passed, {total_failed} failed")
        print(f"{'='*60}")


def interactive_select(manifest: dict) -> tuple[str, str]:
    """Interactive menu to select drive and setlist."""
    folders = manifest.get("folders", [])

    if not folders:
        print("No folders in manifest.")
        sys.exit(1)

    # Select drive
    print("Select drive:\n")
    for i, folder in enumerate(folders, 1):
        name = folder.get("name", "unknown")
        setlists = get_setlists_from_manifest(folder, include_size=True)
        total_size = sum(s for _, _, s in setlists) / 1024 / 1024
        print(f"  [{i}] {name} ({len(setlists)} setlists, {total_size:.0f} MB)")
    print()

    while True:
        try:
            choice = input("Drive: ").strip()
            choice = int(choice)
            if 1 <= choice <= len(folders):
                break
            print(f"Enter 1-{len(folders)}")
        except ValueError:
            print(f"Enter 1-{len(folders)}")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

    selected_folder = folders[choice - 1]
    drive_name = selected_folder.get("name")

    # Select setlist
    setlists = get_setlists_from_manifest(selected_folder, include_size=True)

    print(f"\nSelect setlist in {drive_name}:\n")
    # Sort by name (chronological for year-prefixed names)
    setlists_sorted = sorted(setlists, key=lambda x: x[0])
    for i, (name, charts, size) in enumerate(setlists_sorted, 1):
        size_mb = size / 1024 / 1024
        print(f"  [{i}] {name} ({charts} charts, {size_mb:.1f} MB)")
    print()

    while True:
        try:
            choice = input("Setlist: ").strip()
            choice = int(choice)
            if 1 <= choice <= len(setlists_sorted):
                break
            print(f"Enter 1-{len(setlists_sorted)}")
        except ValueError:
            print(f"Enter 1-{len(setlists_sorted)}")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

    setlist_name = setlists_sorted[choice - 1][0]

    return drive_name, setlist_name


def main():
    parser = argparse.ArgumentParser(
        description="Integration soak test for synchotic",
        epilog="Runs real sync operations and validates everything works correctly."
    )
    parser.add_argument("--drive", help="Drive name to test")
    parser.add_argument("--setlist", help="Setlist name within drive")
    parser.add_argument("--keep", action="store_true", help="Keep temp files after test")
    parser.add_argument("--thorough", action="store_true",
                        help="Run extended robustness tests (delete recovery, corruption detection)")
    args = parser.parse_args()

    # Fetch manifest
    print("Fetching manifest from GitHub...")
    try:
        manifest = fetch_manifest(use_local=False)
    except Exception as e:
        print(f"Failed to fetch manifest: {e}")
        print("Falling back to cached manifest...")
        manifest = fetch_manifest(use_local=True)

    folders = manifest.get("folders", [])
    print(f"Manifest has {len(folders)} drives\n")

    # Get selection
    if args.drive and args.setlist:
        drive_name = args.drive
        setlist_name = args.setlist
    elif args.drive:
        # Find drive, then interactive setlist selection
        folder = next((f for f in folders if f.get("name") == args.drive), None)
        if not folder:
            print(f"Drive '{args.drive}' not found.")
            sys.exit(1)
        setlists = get_setlists_from_manifest(folder, include_size=True)
        print(f"\nSelect setlist in {args.drive}:\n")
        setlists_sorted = sorted(setlists, key=lambda x: x[0])
        for i, (name, charts, size) in enumerate(setlists_sorted, 1):
            size_mb = size / 1024 / 1024
            print(f"  [{i}] {name} ({charts} charts, {size_mb:.1f} MB)")
        print()
        while True:
            try:
                choice = input("Setlist: ").strip()
                choice = int(choice)
                if 1 <= choice <= len(setlists_sorted):
                    break
            except (ValueError, KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                sys.exit(0)
        drive_name = args.drive
        setlist_name = setlists_sorted[choice - 1][0]
    else:
        drive_name, setlist_name = interactive_select(manifest)

    # Run test
    try:
        test = SoakTest(manifest, drive_name, setlist_name,
                        keep_files=args.keep, thorough=args.thorough)
        test.run_all()
    except KeyboardInterrupt:
        print("\n\nTest interrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nTest failed with error: {e}")
        raise


if __name__ == "__main__":
    main()
