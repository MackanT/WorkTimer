"""Tests for form plumbing: conditional visibility (§7.4) and widget coverage."""

import re

from src.ui.work_item_forms import _setup_conditional_visibility
from src.ui.dynamic_widgets import WIDGET_CLASSES


class _FakeElement:
    def __init__(self):
        self.visible = True

    def set_visibility(self, v):
        self.visible = v


class _FakeWidget:
    def __init__(self, value=None):
        self.widget = _FakeElement()
        self.value = value
        self._handlers = []

    def on_value_change(self, handler):
        self._handlers.append(handler)

    def set(self, value):
        self.value = value
        for h in self._handlers:
            h(None)


def test_conditional_visibility_reacts_to_work_item_type():
    """Source/Parent hide based on work item type — silently broken pre-fix."""
    widgets = {
        "work_item_type": _FakeWidget("User Story"),
        "source": _FakeWidget(),
        "parent_name": _FakeWidget(),
    }
    fields = {
        "source": {
            "conditional": True,
            "visible_when": {"work_item_type": ["User Story"]},
        },
        "parent_name": {
            "conditional": True,
            "visible_when": {"work_item_type": ["Feature", "User Story"]},
        },
    }

    _setup_conditional_visibility(widgets, fields, hidden=set())
    # Initial state: User Story shows both.
    assert widgets["source"].widget.visible
    assert widgets["parent_name"].widget.visible

    widgets["work_item_type"].set("Epic")
    assert not widgets["source"].widget.visible
    assert not widgets["parent_name"].widget.visible

    widgets["work_item_type"].set("Feature")
    assert not widgets["source"].widget.visible
    assert widgets["parent_name"].widget.visible


def test_conditional_visibility_noop_without_conditional_fields():
    # Must not blow up when nothing is conditional.
    _setup_conditional_visibility({"a": _FakeWidget()}, {"a": {}}, hidden=set())


def test_widget_classes_cover_every_config_field_type(project_root):
    """Would have caught the missing 'datetime' widget when forms converged."""
    text = (project_root / "config" / "config_ui.yml").read_text(encoding="utf-8")
    types = set(re.findall(r'type:\s*"?([a-z_]+)"?', text))
    missing = types - set(WIDGET_CLASSES)
    assert not missing, f"config field types with no widget class: {missing}"
