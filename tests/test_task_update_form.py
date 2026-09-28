"""Regression (5.1.2): the Update Task form's Status and Priority were blank.

Every dropdown with a parent started with no options (so a parent-filtered
list doesn't show everything before a parent is picked). Status and Priority
have the task selector as parent only to fill in the value — their options are
a fixed list — so they ended up with nothing to show or pick.
"""

import asyncio

import pytest
import yaml
from nicegui import Client, core, ui

from src.pages.tasks import build_form_widgets
from src.ui.dynamic_widgets import DynamicDropDown

STATUSES = ["To Do", "In Progress", "Done"]


@pytest.fixture
def loop(monkeypatch):
    """An event loop NiceGUI also uses, and its default client as the slot to
    build into. Modules using the `user` fixture rebuild that client inside
    their own loop and then close it, which leaves plain test code with
    neither."""
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(core, "loop", loop)
    with Client.auto_index_client:
        yield loop
    # Finish NiceGUI's fire-and-forget tasks first: the `user` fixture's
    # teardown waits for every task NiceGUI created, and one left on a closed
    # loop never completes.
    while pending := asyncio.all_tasks(loop):
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.run_until_complete(asyncio.sleep(0))  # their done-callbacks deregister them
    loop.close()


def _selector():
    return DynamicDropDown(
        name="task_selector", label="Select Task",
        field_config={"options": ["Write docs (ID: 1)"]},
    )


def test_a_value_only_parent_keeps_the_configured_options(loop):
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

    loop.run_until_complete(pick_task())

    assert status.widget.value == "In Progress"
    assert status.widget.options == STATUSES


def test_a_filtering_parent_still_starts_empty(loop):
    """The April fix: options that depend on the parent wait for it."""
    child = DynamicDropDown(
        name="project", label="Project",
        field_config={"options": ["Alpha", "Beta"]}, parent=_selector(),
    )
    assert child.widget.options == []


def test_task_update_form_offers_every_status_and_priority(project_root, loop):
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

    widgets = loop.run_until_complete(build())

    for name in ("status", "priority"):
        assert widgets[name].widget.options == field_map[name]["options"], name
