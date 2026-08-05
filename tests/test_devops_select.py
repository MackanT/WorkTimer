"""Tests for the Git-ID picker: value resolution + the engine option source."""

import logging

import pandas as pd

from src.globals import DevOpsEngine
from src.ui.dynamic_widgets import _devops_id_from_value

LABEL_MAP = {"User Story: 1234 - Fix login": 1234, "Bug: 55 - Crash": 55}

_WORK_ITEMS = pd.DataFrame(
    [
        {"customer_name": "Acme", "display_name": "US: 1 - A", "id": 1, "state": "Active"},
        {"customer_name": "Acme", "display_name": "Bug: 2 - B", "id": 2, "state": "New"},
        {"customer_name": "Acme", "display_name": "US: 3 - C", "id": 3, "state": "Closed"},
        {"customer_name": "Beta", "display_name": "US: 4 - D", "id": 4, "state": "Active"},
    ]
)


def _engine_with(df):
    eng = DevOpsEngine(query_engine=None, log_engine=logging.getLogger("test"))
    eng.df = df
    return eng


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


def test_options_for_customer_filters_active_and_customer():
    # Only Acme's Active/New items — the Closed one and Beta are excluded.
    assert _engine_with(_WORK_ITEMS).get_work_item_options("Acme") == [
        {"label": "US: 1 - A", "id": 1},
        {"label": "Bug: 2 - B", "id": 2},
    ]


def test_options_all_customers_grouped():
    grouped = _engine_with(_WORK_ITEMS).get_work_item_options()
    assert set(grouped) == {"Acme", "Beta"}
    assert len(grouped["Acme"]) == 2
    assert grouped["Beta"] == [{"label": "US: 4 - D", "id": 4}]


def test_options_empty_when_no_devops_data():
    eng = _engine_with(None)
    assert eng.get_work_item_options("Acme") == []
    assert eng.get_work_item_options() == {}
