"""Tests for the Git-ID picker's value resolution (_devops_id_from_value)."""

from src.ui.dynamic_widgets import _devops_id_from_value

LABEL_MAP = {"User Story: 1234 - Fix login": 1234, "Bug: 55 - Crash": 55}


def test_picked_label_maps_to_id():
    assert _devops_id_from_value("User Story: 1234 - Fix login", LABEL_MAP) == 1234


def test_raw_digit_string_is_accepted():
    # Hand-typed id (e.g. DevOps offline) still resolves.
    assert _devops_id_from_value("987", LABEL_MAP) == 987


def test_int_value_passes_through():
    # The select may hold the initial value as a raw int.
    assert _devops_id_from_value(1234, LABEL_MAP) == 1234


def test_empty_and_none_are_none():
    assert _devops_id_from_value("", LABEL_MAP) is None
    assert _devops_id_from_value(None, LABEL_MAP) is None


def test_typed_full_label_extracts_embedded_id():
    assert _devops_id_from_value("Task: 4321 - New thing", {}) == 4321


def test_unparseable_text_is_none():
    assert _devops_id_from_value("no id here", LABEL_MAP) is None
