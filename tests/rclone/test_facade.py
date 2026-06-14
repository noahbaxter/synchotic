# tests/rclone/test_facade.py
from src import rclone

def test_facade_exports():
    assert hasattr(rclone, "is_available")
    assert hasattr(rclone, "RcloneSession")
