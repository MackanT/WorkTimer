"""Tests for multi-project selection helpers in src/devops.py."""

import pandas as pd

from src.devops import _choose_project, _clean_project


def test_clean_project_normalises_blanks_and_sentinels():
    assert _clean_project(None) is None
    assert _clean_project("") is None
    assert _clean_project("   ") is None
    assert _clean_project("none") is None
    assert _clean_project("NULL") is None
    assert _clean_project("nan") is None
    assert _clean_project(float("nan")) is None
    assert _clean_project(pd.NA) is None


def test_clean_project_keeps_real_names_trimmed():
    assert _clean_project("MyProject") == "MyProject"
    assert _clean_project("  Spaces  ") == "Spaces"


AVAILABLE = ["Alpha", "Beta", "Gamma"]


def test_choose_configured_when_present():
    assert _choose_project("Beta", AVAILABLE) == "Beta"


def test_choose_falls_back_to_first_when_configured_missing():
    # Configured project no longer exists in the org -> first (today's default).
    assert _choose_project("Zeta", AVAILABLE) == "Alpha"


def test_choose_defaults_to_first_when_unconfigured():
    assert _choose_project(None, AVAILABLE) == "Alpha"
    assert _choose_project("", AVAILABLE) == "Alpha"


def test_choose_none_when_no_projects():
    assert _choose_project("Beta", []) is None
    assert _choose_project(None, []) is None
