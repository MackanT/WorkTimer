"""Page smoke test: open every page as a simulated user (NiceGUI's `user`
fixture) against a seeded throwaway database.

The user fixture fails a test on any ERROR log, so this catches pages that
break while building — the safety net for Phase 2, which swaps the database
layer underneath every page. Interactions (button clicks) are not covered.

Isolation — this test must never touch real data:
* NiceGUI storage points at a throwaway directory (root conftest.py) and is
  asserted before NiceGUI's fixtures can clear it;
* the app is pointed at a seeded temp database, and teardown asserts that
  data/worktimer.db was never opened;
* the update check and the internet probe are stubbed, so it runs offline.
"""

import asyncio
import logging
from pathlib import Path

import pytest
from nicegui.storage import Storage
from nicegui.testing import User

from src import globals as wt_globals
from src.core import app as core_app
from src.database import Database
from src.pages import root
from src.services import update_checker

from _smoke import PAGES, page_built, seed

# One event loop for the module, as in production: the app keeps module-level
# asyncio.Locks (core/app.py _tracker_init_locks) bound to the first loop
# that uses it, so a fresh loop per test fails with "bound to a different
# event loop" — a harness artifact, not an app bug.
pytestmark = [pytest.mark.module_under_test(root), pytest.mark.asyncio(loop_scope="module")]

ROOT = Path(__file__).resolve().parents[1]
REAL_DB = (ROOT / "data" / "worktimer.db").resolve()
REAL_STORAGE = (ROOT / ".nicegui").resolve()



def _seed(path: Path) -> None:
    lg = logging.getLogger("smoke.seed")
    lg.handlers = [logging.NullHandler()]
    lg.propagate = False
    db = Database(str(path), lg)
    db.initialize_db()
    seed(db)
    db.close()


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("smoke") / "worktimer.db"
    _seed(path)
    yield path
    # Close the app's shared connection so the temp file can be removed.
    for key in [k for k in wt_globals._shared_databases
                if isinstance(k, str) and Path(k).resolve() == path.resolve()]:
        wt_globals._shared_databases.pop(key).close()


@pytest.fixture(autouse=True)
def isolated_app(seeded_db, monkeypatch):
    # Autouse, so this runs before NiceGUI's own fixtures reset — and clear —
    # storage.
    assert Storage.path.resolve() != REAL_STORAGE, (
        "NiceGUI storage points at the real .nicegui/ — its test fixtures would "
        "delete it. The root conftest.py must set NICEGUI_STORAGE_PATH first.")
    monkeypatch.setenv("DB_NAME", str(seeded_db))
    monkeypatch.setattr(core_app, "_config_loaders", {})  # re-read DB_NAME
    monkeypatch.setattr(update_checker, "_fetch_latest_blocking", update_checker._current_version)

    async def offline(self):
        return False  # skips tracker initialisation, which would need network

    monkeypatch.setattr(core_app.AppCore, "_check_internet", offline)
    yield
    opened = {Path(key).resolve() for key in wt_globals._shared_databases if isinstance(key, str)}
    assert REAL_DB not in opened, "a smoke test opened the real data/worktimer.db"


@pytest.mark.parametrize("path", list(PAGES))
async def test_page_renders_without_errors(user: User, path):
    await user.open(path)
    await page_built()
    if PAGES[path]:
        await user.should_see(PAGES[path])


@pytest.mark.parametrize("path, panel", [
    ("/info?tab=excel_import", "excel_import"),  # the Settings card's "How it works"
    ("/settings?tab=data", "data"),  # the Excel import doc's way back
    ("/info?tab=nonsense", "info"),  # an unknown tab: the first
])
async def test_a_link_can_open_a_pages_tab(user: User, path, panel):
    from nicegui import ui

    await user.open(path)
    await page_built()

    [panels] = [e for e in user.client.elements.values() if isinstance(e, ui.tab_panels)]
    assert panels.value == panel


async def test_the_notepad_reopens_the_note_open_last(user: User, tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.testing.user_interaction import UserInteraction

    from src.pages import notepad

    monkeypatch.setattr(notepad, "DATA_DIR", tmp_path)  # never the real data/notes
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "alpha.md").write_text("# Alpha\n\nalpha body text", encoding="utf-8")
    (notes / "beta.md").write_text("# Beta\n\nbeta body text", encoding="utf-8")

    await user.open("/notepad")
    await page_built()
    with user.client:
        [beta] = [e for e in user.client.elements.values()
                  if isinstance(e, ui.label) and e.text == "Beta"]
    UserInteraction(user, {beta.parent_slot.parent}, None).click()  # its sidebar row
    await user.should_see("beta body text")

    await user.open("/notepad")
    await page_built()

    await user.should_see("beta body text")
    await user.should_not_see("alpha body text")


async def test_tracker_customers_are_listed_for_their_contacts(user: User, seeded_db):
    """Settings → Trackers → contacts: a customer linked to a tracker is listed
    without being added by hand — and its Default Assignee card appears even
    with no default yet (a select refused the empty value, and the card
    failed). Last: it links a seeded customer to a tracker."""
    from nicegui import ui

    db = Database(str(seeded_db), logging.getLogger("smoke.seed"))
    db.insert_tracker("Ops DevOps", "devops", org_url="ops", pat_token="pat")
    db.update_customer("Beta", "Beta", tracker_name="Ops DevOps")
    db.close()

    await user.open("/settings")
    await page_built()

    with user.client:
        [customers] = [e for e in user.client.elements.values()
                       if isinstance(e, ui.select) and e.props.get("label") == "Customer"]
    assert customers.options[0] == "Beta"
    await user.should_see("Default Assignee")


def _projects_engine(core, projects: dict, items: list):
    """A TrackerEngine over cached `items` (customer, id, project, title) —
    connections covering `projects` {customer: [main, …]}, none connected
    for real."""
    from collections import defaultdict

    import pandas as pd

    from src.globals import TrackerEngine
    from src.tracker_manager import TrackerManager
    from src.trackers.registry import create_provider_for_row

    log = logging.getLogger("smoke.projects")
    clients = {}
    for customer, names in projects.items():
        client = create_provider_for_row({
            "customer_name": customer, "pat_token": "pat", "org_url": "acme",
            "tracker_project": names[0], "integration_type": "devops"}, log)
        client.projects, client.project_name = list(names), names[0]
        clients[customer] = client
    manager = TrackerManager.__new__(TrackerManager)
    manager.clients, manager.log = clients, log
    engine = TrackerEngine(core.query_engine, log)
    engine.manager, engine.preload_started = manager, True
    engine.columns_cache = defaultdict(dict)
    engine.df = pd.DataFrame([{
        "customer_name": c, "type": "User Story", "id": i, "title": t, "state": "New",
        "parent_id": None, "board_column": "New", "board_column_done": 0, "assigned_to": "",
        "changed_date": "2026-09-01T10:00:00", "priority": 2, "description": "", "project": p,
        "display_name": f"User Story: {i} - {t}"} for c, i, p, t in items])
    return engine


async def test_each_tracker_project_gets_its_own_board_tab(user: User):
    from nicegui import ui

    from src.pages.board import board_page

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    core.tracker_engine = _projects_engine(
        core, {"Acme": ["Platform", "Mobile"], "Beta": ["Ops"]},
        [("Acme", 1, "Platform", "Platform story"), ("Acme", 2, "Mobile", "Mobile story"),
         ("Beta", 3, "Ops", "Beta story")])
    with user.client:
        await board_page()
        tabs = [e.props.get("name") for e in user.client.elements.values() if isinstance(e, ui.tab)]
        [board_tabs] = [e for e in user.client.elements.values()
                        if isinstance(e, ui.tabs) and e.value == "Acme · Platform"]

    assert ["Acme · Platform", "Acme · Mobile", "Beta"] == [t for t in tabs if t in (
        "Acme · Platform", "Acme · Mobile", "Beta")]
    await user.should_see("Platform story")
    await user.should_not_see("Mobile story")

    with user.client:
        board_tabs.value = "Acme · Mobile"
    await user.should_see("Mobile story")
    await user.should_not_see("Platform story")


async def test_the_stop_dialog_picks_the_project_then_its_work_item(user: User):
    from nicegui import ui

    from src.pages.time_tracking import build_devops_selector

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    engine = _projects_engine(
        core, {"Acme": ["Platform", "Mobile"]},
        [("Acme", 1, "Platform", "Platform story"), ("Acme", 2, "Mobile", "Mobile story"),
         ("Acme", 4, "Mobile", "Other mobile story")])

    with user.client:
        id_input, _ = build_devops_selector(engine, "Acme", 2, True)  # its default item: #2
        [project] = [e for e in user.client.elements.values()
                     if isinstance(e, ui.select) and e.props.get("label") == "Tracker project"]

    assert (project.options, project.value) == (["Platform", "Mobile"], "Mobile")
    assert set(id_input.options) == {"User Story: 2 - Mobile story", "User Story: 4 - Other mobile story"}
    assert id_input.value == "User Story: 2 - Mobile story"
    with user.client:
        project.value = "Platform"
    assert list(id_input.options) == ["User Story: 1 - Platform story"]
    assert id_input.value is None


async def test_one_project_customers_get_no_project_choice(user: User):
    from nicegui import ui

    from src.pages.time_tracking import build_devops_selector

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    engine = _projects_engine(core, {"Beta": ["Ops"]}, [("Beta", 3, "Ops", "Beta story")])

    with user.client:
        id_input, _ = build_devops_selector(engine, "Beta", 0, False)
        labels = [e.props.get("label") for e in user.client.elements.values()
                  if isinstance(e, ui.select)]

    assert "Tracker project" not in labels
    assert list(id_input.options) == ["User Story: 3 - Beta story"]


async def test_an_item_added_on_a_project_tab_is_created_in_that_project(user: User):
    from nicegui import ui
    from nicegui.testing.user_interaction import UserInteraction

    from src.ui.work_item_forms import open_add_work_item_dialog

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    core.tracker_engine = engine = _projects_engine(
        core, {"Acme": ["Platform", "Mobile"]},
        [("Acme", 1, "Platform", "Platform story"), ("Acme", 2, "Mobile", "Mobile story")])
    created = []

    def create_item(customer_name, type_key, title, **kwargs):
        created.append((customer_name, type_key, title, kwargs.get("project")))
        return True, "Created User Story with ID 99"

    async def synced(incremental=False):
        pass  # no tracker behind it

    engine.manager.create_item, engine.refresh_tracker_data = create_item, synced
    for key in ("Acme", "Acme · Platform", "Acme · Mobile"):  # no Azure to ask
        engine.columns_cache[key] = {t: ["New", "Active"] for t in ("Epic", "Feature", "User Story")}
    with user.client:
        await open_add_work_item_dialog(core, preset_customer="Acme", preset_project="Mobile")
        inputs = {e.props.get("label"): e for e in user.client.elements.values()
                  if isinstance(e, (ui.input, ui.select))}
    project = inputs["Tracker project"]
    assert (project.value, project.visible) == ("Mobile", True)

    with user.client:
        inputs["Title"].value = "New story"
        priority = inputs["Priority"]
        priority.value = list(priority.options)[0]
        [add] = [e for e in user.client.elements.values()
                 if isinstance(e, ui.button) and e.text == "Add"]
    UserInteraction(user, {add}, None).click()
    for _ in range(60):
        if created:
            break
        await asyncio.sleep(0.05)

    assert created, list(user.notify.messages)
    assert created[0][3] == "Mobile"


def _basic():
    from src.trackers.process import Level, Process

    states = {"To Do": "Proposed", "Doing": "InProgress", "Done": "Completed"}
    return Process((Level("Epics", ("Epic",)), Level("Issues", ("Issue",)),
                    Level("Tasks", ("Task",), tasks=True)),
                   {t: states for t in ("Epic", "Issue", "Task")})


async def _until(check, tries: int = 60):
    for _ in range(tries):
        if check():
            return True
        await asyncio.sleep(0.05)
    return check()


async def test_the_add_form_offers_the_chosen_projects_types_and_states(user: User):
    """A customer's second project on Basic: Epic/Issue/Task with To Do/Doing/
    Done — back on the Agile one, its own levels and states again."""
    from nicegui import ui

    from src.trackers.process import AGILE
    from src.ui.work_item_forms import open_add_work_item_dialog

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    core.tracker_engine = engine = _projects_engine(
        core, {"Acme": ["Platform", "Data"]}, [("Acme", 1, "Platform", "Platform story")])
    engine.manager.clients["Acme"]._processes = {"Platform": AGILE, "Data": _basic()}
    for key, types in (("Acme", AGILE.types), ("Acme · Platform", AGILE.types),
                       ("Acme · Data", ("Epic", "Issue"))):  # no Azure to ask
        engine.columns_cache[key] = {t: ["New", "Active"] for t in types}
    with user.client:
        await open_add_work_item_dialog(core, preset_customer="Acme", preset_project="Data")
        inputs = {e.props.get("label"): e for e in user.client.elements.values()
                  if isinstance(e, (ui.input, ui.select))}
    wtype, state = inputs["Work Item Type"], inputs["State"]

    assert await _until(lambda: list(wtype.options) == ["Epic", "Issue", "Task"]), wtype.options
    assert wtype.value == "Issue"
    assert await _until(lambda: list(state.options) == ["To Do", "Doing", "Done"]), state.options
    assert state.value == "To Do"

    with user.client:
        wtype.value = "Task"
    assert await _until(lambda: inputs["Parent"].visible and not inputs["Source"].visible
                        and not inputs["Initial Board Column"].visible)

    with user.client:
        inputs["Tracker project"].value = "Platform"
    assert await _until(lambda: list(wtype.options) == ["Epic", "Feature", "User Story", "Task"])
    assert await _until(lambda: state.value == "New"), state.value


async def test_the_task_chip_shows_states_and_a_drop_changes_the_state(user: User):
    """Azure has no board for tasks: the Task chip's columns are its states
    (Removed left out, Closed the Done zone), and a drop sets the state."""
    from nicegui import ui
    from nicegui.testing.user_interaction import UserInteraction

    from src.pages.board import board_page
    from src.trackers.process import AGILE

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    core.tracker_engine = engine = _projects_engine(core, {"Beta": ["Ops"]},
                                                    [("Beta", 3, "Ops", "Beta story")])
    engine.manager.clients["Beta"]._processes = {"Ops": AGILE}
    engine.df.loc[len(engine.df)] = {**engine.df.iloc[0].to_dict(), "type": "Task", "id": 7,
                                     "title": "Write tests", "state": "Active", "parent_id": 3,
                                     "board_column": "", "display_name": "Task: 7 - Write tests"}
    engine.columns_cache["Beta"] = {t: ["New", "Active", "Closed"] for t in AGILE.types}
    updated = []

    def update_work_item_fields(customer, work_item_id, fields, markdown=False):
        updated.append((customer, work_item_id, fields))
        return True, "ok"

    async def loaded():
        pass  # nothing in the database behind these items

    engine.manager.update_work_item_fields, engine.load_df = update_work_item_fields, loaded
    with user.client:
        await board_page()
        [chip] = [e for e in user.client.elements.values()
                  if isinstance(e, ui.button) and e.text == "Task"]
    UserInteraction(user, {chip}, None).click()
    await user.should_see("Write tests")

    def column(name):
        return next(e for e in user.client.elements.values()
                    if isinstance(e, ui.card) and "board-col" in e.classes
                    and any(isinstance(d, ui.label) and d.text == name for d in e.descendants()))

    with user.client:
        columns = [d.text for e in user.client.elements.values()
                   if isinstance(e, ui.card) and "board-col" in e.classes
                   for d in e.descendants() if isinstance(d, ui.label)
                   and "font-semibold" in d.classes]
        [card] = [e for e in user.client.elements.values()
                  if isinstance(e, ui.card) and "board-card" in e.classes]
    assert columns[:2] == ["New", "Active"] and "Removed" not in columns
    UserInteraction(user, {card}, None).trigger("dragstart")
    UserInteraction(user, {column("New")}, None).trigger("drop")

    assert await _until(lambda: updated), list(user.notify.messages)
    assert updated == [("Beta", 7, {"System.State": "New"})]
    assert engine.df.set_index("id").loc[7, "state"] == "New"


async def test_a_card_lists_its_open_children_and_its_plus_adds_one(user: User):
    """A story's open tasks fold into "1 Task" under its card — the closed one
    left out — that a click opens; its ＋ opens the add form for a Task under it."""
    from nicegui import ui
    from nicegui.testing.user_interaction import UserInteraction

    from src.pages.board import board_page
    from src.trackers.process import AGILE

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    core.tracker_engine = engine = _projects_engine(core, {"Beta": ["Ops"]},
                                                    [("Beta", 3, "Ops", "Beta story")])
    engine.manager.clients["Beta"]._processes = {"Ops": AGILE}
    story = engine.df.iloc[0].to_dict()
    for wid, title, st in ((7, "Write tests", "Active"), (8, "Old task", "Closed")):
        engine.df.loc[len(engine.df)] = {**story, "type": "Task", "id": wid, "title": title,
                                         "state": st, "parent_id": 3, "board_column": "",
                                         "display_name": f"Task: {wid} - {title}"}
    engine.columns_cache["Beta"] = {t: ["New", "Active", "Closed"] for t in AGILE.types}
    with user.client:
        await board_page()
    await user.should_see("1 Task")
    await user.should_not_see("Write tests")

    def stopped(element) -> bool:
        return any(lis.type == "click.stop" for lis in element._event_listeners.values())

    with user.client:
        [count_line] = [e.parent_slot.parent for e in user.client.elements.values()
                        if isinstance(e, ui.label) and e.text == "1 Task"]
    UserInteraction(user, {count_line}, None).trigger("click.stop")
    await user.should_see("Write tests")
    await user.should_not_see("Old task")

    with user.client:
        [plus] = [e for e in user.client.elements.values()
                  if isinstance(e, ui.button) and e.props.get("icon") == "add" and stopped(e)]
    UserInteraction(user, {plus}, None).trigger("click.stop")

    def inputs():
        return {e.props.get("label"): e for e in user.client.elements.values()
                if isinstance(e, (ui.input, ui.select))}

    assert await _until(lambda: "Parent" in inputs()
                        and inputs()["Work Item Type"].value == "Task"
                        and inputs()["Parent"].value == "User Story: 3 - Beta story"), {
        k: getattr(v, "value", None) for k, v in inputs().items()}


async def test_the_stop_dialog_offers_open_items_of_any_process_tasks_included(user: User):
    from src.pages.time_tracking import build_devops_selector
    from src.trackers.process import AGILE

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    engine = _projects_engine(
        core, {"Acme": ["Platform", "Data"]},
        [("Acme", 1, "Platform", "Story"), ("Acme", 2, "Platform", "Done story"),
         ("Acme", 3, "Platform", "A task"), ("Acme", 4, "Data", "Doing issue"),
         ("Acme", 5, "Data", "Done issue")])
    engine.manager.clients["Acme"]._processes = {"Platform": AGILE, "Data": _basic()}
    engine.df["type"] = ["User Story", "User Story", "Task", "Issue", "Issue"]
    engine.df["state"] = ["Active", "Resolved", "New", "Doing", "Done"]
    engine.df["state_category"] = engine._state_categories(engine.df)
    engine.df["display_name"] = [f"{t}: {i} - {n}" for t, i, n in
                                 zip(engine.df["type"], engine.df["id"], engine.df["title"])]

    with user.client:
        id_input, _ = build_devops_selector(engine, "Acme", 0, False)
    assert list(id_input.options) == ["Task: 3 - A task", "User Story: 1 - Story"]

    with user.client:
        project = next(e for e in user.client.elements.values()
                       if getattr(e, "props", {}).get("label") == "Tracker project")
        project.value = "Data"
    assert list(id_input.options) == ["Issue: 4 - Doing issue"]


async def test_a_datetime_field_reads_the_same_on_every_computer(user: User):
    """Typed or picked, always 'YYYY-MM-DD HH:MM' in 24 hours — a native
    datetime-local field showed AM/PM on PCs set up that way."""
    from nicegui import ui

    from src.ui.elements import datetime_input

    await user.open("/time")
    await page_built()
    changes = []
    with user.client:
        field = datetime_input("Stop time", "2026-11-09 14:30",
                               on_change=lambda e: changes.append(e.value))
        clock = next(e for e in field.descendants() if isinstance(e, ui.time))
        calendar = next(e for e in field.descendants() if isinstance(e, ui.date))

    assert field.props["type"] == "text" and field.props["mask"] == "####-##-## ##:##"
    assert "format24h" in clock.props and calendar.value == "2026-11-09 14:30"
    with user.client:
        field.value = "2026-11-0"  # still typing
        clock.value = "2026-11-09 16:05"
    assert changes == ["2026-11-09 16:05"] and field.value == "2026-11-09 16:05"


async def test_an_edited_add_dialog_stays_open_and_cancel_asks_first(user: User):
    from nicegui import ui
    from nicegui.testing.user_interaction import UserInteraction

    from src.ui.work_item_forms import open_add_work_item_dialog

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    core.tracker_engine = engine = _projects_engine(core, {"Beta": ["Ops"]},
                                                    [("Beta", 3, "Ops", "Beta story")])
    engine.columns_cache["Beta"] = {t: ["New", "Active"] for t in ("Epic", "Feature", "User Story")}
    with user.client:
        dlg = await open_add_work_item_dialog(core, preset_customer="Beta")
        title = next(e for e in dlg.descendants()
                     if isinstance(e, ui.input) and e.props.get("label") == "Title")
        [cancel] = [e for e in dlg.descendants() if isinstance(e, ui.button) and e.text == "Cancel"]
    assert "persistent" not in dlg.props  # untouched: a click outside still closes it

    UserInteraction(user, {title}, None).trigger(f"update:{title.VALUE_PROP}")  # typed
    assert "persistent" in dlg.props
    UserInteraction(user, {cancel}, None).click()
    await user.should_see("Discard unsaved changes?")
    assert dlg.value  # still open until Discard
