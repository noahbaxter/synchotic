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


@pytest.fixture(scope="session", autouse=True)
def verify_fixtures_exist():
    """Verify test fixtures exist, skip integration tests if not."""
    if not FIXTURES_DIR.exists():
        pytest.skip(
            "Integration test fixtures not found. "
            "Run: python scripts/generate_test_fixtures.py"
        )
    archives = list(FIXTURES_DIR.glob("*.zip"))
    if not archives:
        pytest.skip(
            "No test archives found. "
            "Run: python scripts/generate_test_fixtures.py"
        )
