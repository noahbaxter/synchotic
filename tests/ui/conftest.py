"""Shared chart data for the sync screen tests."""
import pytest

from .chart_fixture import new_seed, sample


@pytest.fixture
def seed():
    """A fresh seed each run, printed so a failure can be reproduced.

    pytest shows captured stdout for failing tests only, so this is silent
    until something breaks.
    """
    value = new_seed()
    print(f"chart fixture seed={value}")
    return value


@pytest.fixture
def charts(seed):
    """120 charts drawn at random from the master list."""
    return sample(120, seed)
