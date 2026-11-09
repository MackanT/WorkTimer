"""Each Azure DevOps project's own process — Basic, Agile, Scrum, CMMI or
custom: its levels, boards and states read from the project, the sync and
create following them, Agile when Azure won't say — against a fake SDK."""

import logging
from collections import defaultdict
from types import SimpleNamespace

import pandas as pd
import pytest

from src import tracker_manager
from src.trackers import process as proc
from src.trackers.azure import AzureDevOpsProvider  # noqa: F401 — registers "devops"
from src.trackers.registry import create_provider_for_row
from src.tracker_manager import TrackerManager

_log = logging.getLogger("test_tracker_process")


def _backlog(name, types, rank, default=None):
    return SimpleNamespace(name=name, rank=rank,
                           work_item_types=[SimpleNamespace(name=t) for t in types],
                           default_work_item_type=SimpleNamespace(name=default or types[0]))


def _config(portfolio, requirement, task):
    return SimpleNamespace(portfolio_backlogs=portfolio, requirement_backlog=requirement,
                           task_backlog=task)


def _types(states: dict):
    return [SimpleNamespace(name=t, states=[SimpleNamespace(name=s, category=c)
                                            for s, c in ss])
            for t, ss in states.items()]


_BASIC_STATES = [("To Do", "Proposed"), ("Doing", "InProgress"), ("Done", "Completed")]
BASIC = (
    _config([_backlog("Epics", ["Epic"], 3)], _backlog("Issues", ["Issue"], 2),
            _backlog("Tasks", ["Task"], 1)),
    _types({"Epic": _BASIC_STATES, "Issue": _BASIC_STATES, "Task": _BASIC_STATES,
            "Test Case": [("Design", "Proposed")]}),
)
_AGILE_STATES = [("New", "Proposed"), ("Active", "InProgress"), ("Resolved", "InProgress"),
                 ("Closed", "Completed"), ("Removed", "Removed")]
AGILE_WITH_BUGS = (
    _config([_backlog("Features", ["Feature"], 3), _backlog("Epics", ["Epic"], 4)],
            _backlog("Stories", ["User Story"], 2), _backlog("Tasks", ["Task", "Bug"], 1)),
    _types({"Epic": _AGILE_STATES, "Feature": _AGILE_STATES, "User Story": _AGILE_STATES,
            "Task": [("New", "Proposed"), ("Active", "InProgress"), ("Closed", "Completed")],
            "Bug": [("New", "Proposed"), ("Active", "InProgress"), ("Resolved", "Resolved"),
                    ("Closed", "Completed")]}),
)


class FakeWit:
    def __init__(self, items, types):
        self.items, self.types, self.calls = items, types, []

    def get_work_item_types(self, project):
        return self.types[project]

    def query_by_wiql(self, wiql):
        return SimpleNamespace(work_items=[SimpleNamespace(id=i) for i in self.items])

    def get_work_items(self, ids, expand=None):
        return [SimpleNamespace(id=i, fields={
            "System.WorkItemType": self.items[i][1], "System.Title": f"Item {i}",
            "System.State": "To Do", "System.TeamProject": self.items[i][0],
            "System.Parent": 1}) for i in ids]

    def create_work_item(self, document, project, type):
        self.calls.append((project, type, any(op["path"] == "/relations/-" for op in document)))
        return SimpleNamespace(id=900)


@pytest.fixture
def connect(monkeypatch):
    """A connected provider for customer Acme over `processes` {project:
    (config, types) — or an exception}, the first project the main one."""

    def _connect(processes: dict, items=None):
        wit = FakeWit(items or {}, {p: v[1] for p, v in processes.items()
                                    if not isinstance(v, Exception)})
        names = list(processes)
        core = SimpleNamespace(get_projects=lambda: [SimpleNamespace(name=n) for n in names])

        def backlogs(team_context):
            value = processes[team_context.project]
            if isinstance(value, Exception):
                raise value
            return value[0]

        work = SimpleNamespace(get_backlog_configurations=backlogs)

        class FakeConnection:
            def __init__(self, base_url, creds):
                self.clients = SimpleNamespace(get_core_client=lambda: core,
                                               get_work_item_tracking_client=lambda: wit,
                                               get_work_client=lambda: work)

        monkeypatch.setattr(tracker_manager, "Connection", FakeConnection)
        provider = create_provider_for_row({
            "customer_name": "Acme", "pat_token": "pat", "org_url": "acme",
            "tracker_project": names[0], "extra_tracker_projects": names[1:],
            "integration_type": "devops"}, _log)
        provider.connect()
        return provider, wit

    return _connect


def test_a_basic_project_has_epics_issues_and_tasks():
    basic = proc.from_azure(*BASIC)

    assert basic.types == ("Epic", "Issue") and basic.task_types == ("Task",)
    assert basic.working_type == "Issue" and basic.root_types == ("Epic",)
    assert (basic.board("Issue"), basic.board("Task")) == ("Issues", None)
    assert basic.state_options("Issue") == ["To Do", "Doing", "Done"]
    assert "Test Case" not in basic.states  # on no backlog level


def test_levels_run_from_the_highest_rank_and_every_type_on_one_counts():
    agile = proc.from_azure(*AGILE_WITH_BUGS)

    assert agile.types == ("Epic", "Feature", "User Story")
    assert agile.task_types == ("Task", "Bug")
    assert agile.state_options() == ["New", "Active", "Resolved", "Closed", "Removed"]


def test_a_levels_default_type_comes_first():
    config = _config([], _backlog("Backlog items", ["Bug", "Product Backlog Item"], 2,
                                  default="Product Backlog Item"), None)

    assert proc.from_azure(config, []).types == ("Product Backlog Item", "Bug")


def test_open_means_proposed_or_in_progress_but_never_resolved():
    agile = proc.from_azure(*AGILE_WITH_BUGS)

    assert [s for s in agile.state_options("User Story")
            if proc.is_open(s, agile.category("User Story", s))] == ["New", "Active"]
    assert not proc.is_open("Resolved", agile.category("Bug", "Resolved"))
    assert proc.is_open("In Review", None)  # unknown: still open, as before
    assert not proc.is_open("Done", proc.guess_category("Done"))


def test_each_project_reads_its_own_process_and_a_failed_read_assumes_agile(connect, caplog):
    provider, _ = connect({"Home": AGILE_WITH_BUGS, "Data": BASIC,
                           "Old": RuntimeError("TF400813: not authorized")})

    assert provider.process().working_type == "User Story"
    assert provider.process("Data").types == ("Epic", "Issue")
    assert provider.process("Old") is proc.AGILE
    assert provider.process("Not linked") is provider.process("Home")
    assert "Could not read the process of DevOps project 'Old'" in caplog.text


def test_the_sync_keeps_each_projects_own_levels_tasks_included(connect):
    provider, _ = connect({"Home": AGILE_WITH_BUGS, "Data": BASIC}, items={
        1: ("Data", "Epic"), 2: ("Data", "Issue"), 3: ("Data", "Task"),
        4: ("Data", "Test Case"), 5: ("Home", "Bug"), 6: ("Home", "Issue")})

    df = provider.fetch_work_items()

    assert dict(zip(df["id"], df["type"])) == {1: "Epic", 2: "Issue", 3: "Task", 5: "Bug"}
    assert df.set_index("id")["parent_id"].isna().to_dict() == {
        1: True, 2: False, 3: False, 5: False}


def test_any_level_can_be_created_and_the_root_takes_no_parent(connect):
    provider, wit = connect({"Home": AGILE_WITH_BUGS, "Data": BASIC})

    provider.create_item("Epic", "Big", parent=5, project="Data")
    provider.create_item("Issue", "Small", parent=5, project="Data")
    provider.create_item("Task", "Tiny", parent=6, project="Home")

    assert wit.calls == [("Data", "Epic", False), ("Data", "Issue", True),
                         ("Home", "Task", True)]


# ── the engine ──────────────────────────────────────────────────────────────


def _engine(provider, items=()):
    from src.globals import TrackerEngine

    manager = TrackerManager.__new__(TrackerManager)
    manager.clients, manager.log = {"Acme": provider}, _log
    engine = TrackerEngine.__new__(TrackerEngine)
    engine.manager, engine.log = manager, _log
    engine.df = pd.DataFrame([{"customer_name": "Acme", "id": i, "project": p, "type": t,
                               "state": s} for i, p, t, s in items],
                             columns=["customer_name", "id", "project", "type", "state"])
    return engine


def test_the_engine_answers_per_project(connect):
    engine = _engine(connect({"Home": AGILE_WITH_BUGS, "Data": BASIC})[0])

    assert engine.type_hierarchy("Acme") == ("Epic", "Feature", "User Story")
    assert engine.type_hierarchy("Acme", "Data") == ("Epic", "Issue")
    assert engine.preferred_type("Acme", "Data") == "Issue"
    assert engine.task_types("Acme") == ("Task", "Bug")
    assert engine.state_options("Acme", "Data", "Task") == ["To Do", "Doing", "Done"]
    assert engine.state_options("Acme", "Data") == ["To Do", "Doing", "Done"]


def test_each_cached_item_gets_its_state_category(connect):
    engine = _engine(connect({"Home": AGILE_WITH_BUGS, "Data": BASIC})[0], [
        (1, "Data", "Issue", "Done"), (2, "Home", "User Story", "Resolved"),
        (3, "Home", "Bug", "Resolved"), (4, None, "Task", "New"), (5, "Home", "Task", "Odd")])

    assert engine._state_categories(engine.df).tolist() == [
        "Completed", "InProgress", "Resolved", "Proposed", None]


def test_offline_a_state_category_is_guessed_from_its_name():
    engine = _engine(None, [(1, "Data", "Issue", "Done"), (2, "Data", "Issue", "Doing")])
    engine.manager = None

    assert engine._state_categories(engine.df).tolist() == ["Completed", "InProgress"]


async def test_a_project_whose_tasks_were_never_synced_is_fetched_in_full_once(connect):
    provider, _ = connect({"Data": BASIC})
    engine = _engine(provider, [(1, "Data", "Epic", "To Do"), (2, "Data", "Issue", "To Do")])
    engine._fully_fetched = set()

    assert await engine._unsynced_customers() == {"Acme"}
    engine._fully_fetched.add(("Acme", "Data"))
    assert await engine._unsynced_customers() == set()

    engine._fully_fetched = set()
    engine.df.loc[len(engine.df)] = ["Acme", 3, "Data", "Task", "To Do"]
    assert await engine._unsynced_customers() == set()


def test_board_columns_come_from_the_board_the_process_names(connect):
    from src.ui.work_item_handlers import WorkItemHandlers

    provider, _ = connect({"Home": AGILE_WITH_BUGS, "Data": BASIC})
    asked = []
    provider.get_board_columns_via_team_autodetect = lambda board_type, project=None: (
        asked.append((board_type, project)), (True, ["To Do", "Doing", "Done"]))[1]
    engine = _engine(provider)
    engine.columns_cache, engine.preload_started = defaultdict(dict), True

    handlers = WorkItemHandlers(engine, _log)

    assert handlers.load_board_columns("Acme", "Issue", "Data", "Acme · Data") == (
        ["To Do", "Doing", "Done"], True)
    assert handlers.load_board_columns("Acme", "Task", "Data", "Acme · Data") is None
    assert asked == [("Issues", "Data")]
