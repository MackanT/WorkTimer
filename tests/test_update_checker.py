"""Tests for the update-checker version comparison (_is_newer)."""

import pytest

from src.services.update_checker import _is_newer


@pytest.mark.parametrize(
    "latest, current, expected",
    [
        ("5.0.3", "5.0.2", True),    # a real upgrade
        ("5.0.2", "5.0.3", False),   # local build ahead of main → no downgrade badge
        ("5.0.2", "5.0.2", False),   # identical
        ("5.0.10", "5.0.2", True),   # semver, not string ('5.0.10' < '5.0.2' lexically)
        ("5.1.0", "5.0.9", True),    # minor bump
        ("6.0.0", "5.9.9", True),    # major bump
        ("5.0.2", "unknown", False), # current unreadable → can't compare
        ("", "5.0.2", False),        # no latest
    ],
)
def test_is_newer(latest, current, expected):
    assert _is_newer(latest, current) is expected
