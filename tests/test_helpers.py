"""Tests for pure utilities in src/helpers.py."""

from datetime import date

import pandas as pd

from src import helpers


def test_get_range_for_day():
    today = date.today()
    assert helpers.get_range_for("Day") == f"{today} - {today}"


def test_get_range_for_unknown_is_empty():
    assert helpers.get_range_for("nope") == ""


def test_parse_date_range_variants():
    assert helpers.parse_date_range("2025-01-01 - 2025-01-31") == ("20250101", "20250131")
    assert helpers.parse_date_range("20250101 - 20250131") == ("20250101", "20250131")
    assert helpers.parse_date_range("garbage") == (None, None)
    assert helpers.parse_date_range("") == (None, None)


def test_extract_devops_id():
    assert helpers.extract_devops_id("Epic: 123 - Title") == 123
    assert helpers.extract_devops_id("no id here") is None
    assert helpers.extract_devops_id(None) is None


def test_extract_id_from_text_custom_pattern():
    assert helpers.extract_id_from_text("Task #456", pattern=r"#(\d+)") == 456


def test_extract_table_name():
    assert helpers.extract_table_name("select * from time where x=1") == "time"
    assert helpers.extract_table_name("select 1 where x=1") == "unknown_table"


def test_has_dataframe_data():
    assert helpers.has_dataframe_data(pd.DataFrame({"a": [1]}))
    assert not helpers.has_dataframe_data(pd.DataFrame())
    assert not helpers.has_dataframe_data(None)


class _Widget:
    def __init__(self, value):
        self.value = value


class _Chip:
    def __init__(self, text, selected):
        self.text = text
        self.selected = selected


def test_parse_widget_values_handles_chip_group():
    widgets = {
        "name": _Widget("x"),
        "tags": [_Chip("a", True), _Chip("b", False), _Chip("c", True)],
    }
    vals = helpers.parse_widget_values(widgets)
    assert vals["name"] == "x"
    assert vals["tags"] == ["a", "c"]


def test_check_input_chip_group_selection(monkeypatch):
    # check_input calls ui.notify on failure — stub it out (no client context in tests).
    monkeypatch.setattr(helpers.ui, "notify", lambda *a, **k: None)

    empty = {"tags": [_Chip("a", False)]}
    assert helpers.check_input(empty, ["tags"]) is False

    chosen = {"tags": [_Chip("a", True)]}
    assert helpers.check_input(chosen, ["tags"]) is True


def test_check_input_treats_zero_and_false_as_present(monkeypatch):
    monkeypatch.setattr(helpers.ui, "notify", lambda *a, **k: None)
    widgets = {"n": _Widget(0), "b": _Widget(False)}
    assert helpers.check_input(widgets, ["n", "b"]) is True


def test_assign_dynamic_options_fills_from_source():
    fields = [
        {"name": "c", "type": "select", "options": [], "options_source": "customer_data"}
    ]
    helpers.assign_dynamic_options(fields, {"customer_data": ["A", "B"]})
    assert fields[0]["options"] == ["A", "B"]
