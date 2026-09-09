"""Tests for the update-checker version comparison (_is_newer) and the
what's-new changelog section extraction."""

import pytest

from src.services.update_checker import _is_newer, extract_whats_new

_CHANGELOG = """## Changelog
### 5.0.5 (2026-xx-xx)
- new palette feature

### 5.0.4 (2026-09-01)
- board search

### 5.0.3 (2026-08-11)
- reports dashboard
"""


def test_extract_whats_new_returns_only_newer_sections():
    out = extract_whats_new(_CHANGELOG, "5.0.3")
    assert "5.0.5" in out and "new palette feature" in out
    assert "5.0.4" in out and "board search" in out
    assert "reports dashboard" not in out


def test_extract_whats_new_nothing_newer():
    assert extract_whats_new(_CHANGELOG, "5.0.5") == ""
    assert extract_whats_new("", "5.0.3") == ""


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
