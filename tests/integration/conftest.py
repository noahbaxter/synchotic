"""Pytest configuration for integration tests."""

import pytest
from pathlib import Path


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "test_archives"


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: integration tests (may do I/O)"
    )
    config.addinivalue_line(
        "markers", "e2e: end-to-end tests (require network)"
    )
    config.addinivalue_line(
        "markers", "scheduled: tests that run on schedule, not every push"
    )
    config.addinivalue_line(
        "markers", "needs_fixtures: tests that require generated archive fixtures"
    )


@pytest.fixture(scope="session")
def archive_fixtures():
    """Provide path to archive fixtures, skip if not generated."""
    if not FIXTURES_DIR.exists() or not list(FIXTURES_DIR.glob("*.zip")):
        pytest.skip(
            "Integration test fixtures not found. "
            "Run: python scripts/generate_test_fixtures.py"
        )
    return FIXTURES_DIR
