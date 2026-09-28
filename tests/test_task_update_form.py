"""Regression (5.1.2): the Update Task form's Status and Priority were blank.

Every dropdown with a parent started with no options (so a parent-filtered
list doesn't show everything before a parent is picked). Status and Priority
have the task selector as parent only to fill in the value — their options are
a fixed list — so they ended up with nothing to show or pick.
"""

import asyncio

import yaml
from nicegui import ui

from src.pages.tasks import build_form_widgets
from src.ui.dynamic_widgets import DynamicDropDown

STATUSES = ["To Do", "In Progress", "Done"]


def _selector():
    return DynamicDropDown(
        name="task_selector", label="Select Task",
        field_config={"options": ["Write docs (ID: 1)"]},
    )


def test_a_value_only_parent_keeps_the_configured_options():
    parent = _selector()

    async def fetch(_field, parent_val):
        return "In Progress" if parent_val else None

    status = DynamicDropDown(
        name="status", label="Status",
        field_config={"options": STATUSES, "parent_update": True},
        data_fetcher=fetch, parent=parent,
    )
    assert status.widget.options == STATUSES

    async def pick_task():
        parent.widget.value = "Write docs (ID: 1)"
        await status.refresh()

    asyncio.run(pick_task())

    assert status.widget.value == "In Progress"
    assert status.widget.options == STATUSES


def test_a_filtering_parent_still_starts_empty():
    """The April fix: options that depend on the parent wait for it."""
    child = DynamicDropDown(
        name="project", label="Project",
        field_config={"options": ["Alpha", "Beta"]}, parent=_selector(),
    )
    assert child.widget.options == []


def test_task_update_form_offers_every_status_and_priority(project_root):
    cfg = yaml.safe_load(
        (project_root / "config" / "config_ui.yml").read_text(encoding="utf-8")
    )["task"]["update"]
    field_map = {f["name"]: f for f in cfg["fields"]}

    async def fetch(_field, _parent_val):
        return None

    host = ui.column()  # a slot to build into from the event loop's task

    async def build():
        with host:
            return build_form_widgets(
                rows_layout=cfg["rows"], field_map=field_map, data_fetcher=fetch,
                page_state={}, main_param="task_selector", pending_loads=[],
            )

    widgets = asyncio.run(build())

    for name in ("status", "priority"):
        assert widgets[name].widget.options == field_map[name]["options"], name
