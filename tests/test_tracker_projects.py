"""Several tracker projects per customer (Azure DevOps, one org): the
connection covers them all, one query syncs them, each item keeps its
project, and every per-item call reaches that project — against a fake
Azure DevOps SDK."""

import logging
from types import SimpleNamespace

import pytest

from src import tracker_manager
from src.trackers.azure import AzureDevOpsProvider  # noqa: F401 — registers "devops"
from src.trackers.registry import create_provider_for_row
from src.tracker_manager import TrackerManager

_log = logging.getLogger("test_tracker_projects")


class FakeWit:
    """The work-item-tracking client: records calls, answers from `items`."""

    def __init__(self, items: dict):
        self.items = items  # id → (project, type)
        self.calls = []

    def query_by_wiql(self, wiql):
        self.calls.append(("wiql", wiql["query"]))
        return SimpleNamespace(work_items=[SimpleNamespace(id=i) for i in self.items])

    def get_work_items(self, ids, expand=None):
        return [SimpleNamespace(id=i, fields={
            "System.WorkItemType": self.items[i][1], "System.Title": f"Item {i}",
            "System.State": "New", "System.TeamProject": self.items[i][0]}) for i in ids]

    def get_work_item(self, wid, fields=None, expand=None):
        self.calls.append(("lookup", wid))
        return SimpleNamespace(fields={"System.TeamProject": self.items[wid][0]})

    def add_comment(self, request, project, work_item_id):
        self.calls.append(("comment", project, work_item_id))

    def get_comments(self, project, work_item_id):
        self.calls.append(("comments", project, work_item_id))
        return SimpleNamespace(comments=[])

    def update_work_item(self, document, id, project=None):
        self.calls.append(("update", project, id))

    def create_work_item(self, document, project, type):
        self.calls.append(("create", project, type, document))
        return SimpleNamespace(id=900)


@pytest.fixture
def connect(monkeypatch):
    """Build and connect a customer's provider against an org with the given
    projects; returns (provider, fake wit client)."""

    def _connect(main="Platform", extra=(), org_projects=("Platform", "Mobile", "Data"),
                 items=None):
        wit = FakeWit(items or {})
        core = SimpleNamespace(get_projects=lambda: [SimpleNamespace(name=n) for n in org_projects])

        class FakeConnection:
            def __init__(self, base_url, creds):
                self.clients = SimpleNamespace(get_core_client=lambda: core,
                                               get_work_item_tracking_client=lambda: wit)

        monkeypatch.setattr(tracker_manager, "Connection", FakeConnection)
        provider = create_provider_for_row({
            "customer_name": "Acme", "pat_token": "pat", "org_url": "acme",
            "tracker_project": main, "extra_tracker_projects": list(extra),
            "integration_type": "devops"}, _log)
        provider.connect()
        return provider, wit

    return _connect


def test_the_linked_projects_found_in_the_org_are_covered_main_first(connect, caplog):
    provider, _ = connect(extra=["Mobile", "Gone", "Platform", "Mobile"])

    assert provider.projects == ["Platform", "Mobile"]
    assert "Linked DevOps project 'Gone' not found" in caplog.text


def test_one_query_syncs_every_project_and_each_item_keeps_its_own(connect):
    provider, wit = connect(extra=["Mobile", "O'Brien"],
                            org_projects=("Platform", "Mobile", "O'Brien"),
                            items={1: ("Platform", "Epic"), 2: ("Mobile", "User Story")})

    df = provider.fetch_work_items()

    [(_, query)] = [c for c in wit.calls if c[0] == "wiql"]
    assert "[System.TeamProject] IN ('Platform', 'Mobile', 'O''Brien')" in query
    assert dict(zip(df["id"], df["project"])) == {1: "Platform", 2: "Mobile"}


def test_per_item_calls_reach_the_items_project(connect):
    provider, wit = connect(extra=["Mobile"],
                            items={1: ("Platform", "Epic"), 2: ("Mobile", "User Story")})
    provider.fetch_work_items()
    wit.calls.clear()

    provider.add_comment_to_work_item(2, "Done")
    provider.update_work_item_fields(2, {"System.Title": "Renamed"})
    provider.get_work_item_comments(1)

    assert wit.calls == [("comment", "Mobile", 2), ("update", "Mobile", 2),
                         ("comments", "Platform", 1)]
    assert provider.get_work_item_url(2) == "https://dev.azure.com/acme/Mobile/_workitems/edit/2"


def test_an_item_the_sync_hasnt_seen_is_looked_up_once(connect):
    provider, wit = connect(extra=["Mobile"], items={7: ("Mobile", "User Story")})

    provider.add_comment_to_work_item(7, "One")
    provider.add_comment_to_work_item(7, "Two")

    assert wit.calls == [("lookup", 7), ("comment", "Mobile", 7), ("comment", "Mobile", 7)]


def test_a_customer_with_one_project_never_looks_anything_up(connect):
    provider, wit = connect(items={7: ("Platform", "User Story")})

    provider.add_comment_to_work_item(7, "Hi")

    assert provider.projects == ["Platform"]
    assert wit.calls == [("comment", "Platform", 7)]


def test_an_item_is_created_in_the_chosen_project(connect):
    provider, wit = connect(extra=["Mobile"])

    provider.create_item("User Story", "New", parent=5, project="Mobile")
    provider.create_item("Epic", "Elsewhere", project="Not linked")  # → the main one

    (_, project, wtype, document), (_, other, _, _) = [c for c in wit.calls if c[0] == "create"]
    assert (project, wtype, other) == ("Mobile", "User Story", "Platform")
    parent = next(op for op in document if op["path"] == "/relations/-")
    assert parent["value"]["url"] == "https://dev.azure.com/acme/_apis/wit/workItems/5"
    assert provider.project_for(900) == "Platform"  # remembered: the latest create


def test_the_manager_passes_the_project_through(connect, monkeypatch):
    provider, wit = connect(extra=["Mobile"], items={2: ("Mobile", "User Story")})
    manager = TrackerManager.__new__(TrackerManager)
    manager.clients, manager.log = {"Acme": provider}, _log
    urls = []
    monkeypatch.setattr(tracker_manager.requests, "get", lambda url, **kw: (
        urls.append(url), SimpleNamespace(status_code=200, json=lambda: {"value": []}))[1])

    manager.create_item("Acme", "User Story", "New", project="Mobile")
    manager.list_repositories("Acme", work_item_id=2)
    manager.list_repositories("Acme", project="Platform")

    assert manager.projects("Acme") == ["Platform", "Mobile"]
    assert ("create", "Mobile", "User Story") == [c for c in wit.calls if c[0] == "create"][0][:3]
    assert [u.split("/_apis")[0] for u in urls] == ["https://dev.azure.com/acme/Mobile",
                                                     "https://dev.azure.com/acme/Platform"]


# ── the engine: Board tabs and pickers per project ─────────────────────────


def _engine(projects: dict, items: list):
    """A TrackerEngine over `items` (customer, id, project) with connections
    covering `projects` {customer: [main, …]} — nothing connected for real."""
    import pandas as pd

    from src.globals import TrackerEngine

    clients = {}
    for customer, names in projects.items():
        client = create_provider_for_row({
            "customer_name": customer, "pat_token": "pat", "org_url": "acme",
            "tracker_project": names[0], "integration_type": "devops"}, _log)
        client.projects, client.project_name = list(names), names[0]
        clients[customer] = client
    manager = TrackerManager.__new__(TrackerManager)
    manager.clients, manager.log = clients, _log
    engine = TrackerEngine.__new__(TrackerEngine)
    engine.manager = manager
    engine.df = pd.DataFrame([{"customer_name": c, "id": i, "project": p, "state": "New",
                               "display_name": f"User Story: {i} - Item {i}"}
                              for c, i, p in items])
    return engine


def test_a_customer_with_several_projects_gets_a_board_tab_per_project():
    engine = _engine({"Acme": ["Platform", "Mobile"], "Beta": ["Ops"], "Gamma": ["X", "Y"]},
                     [("Acme", 1, "Platform"), ("Beta", 2, "Ops")])

    assert engine.boards() == [
        ("Acme · Platform", "Acme", "Platform"), ("Acme · Mobile", "Acme", "Mobile"),
        ("Beta", "Beta", None),
        ("Gamma · X", "Gamma", "X"), ("Gamma · Y", "Gamma", "Y"),  # no items yet: still tabs
    ]


def test_offline_the_projects_come_from_the_cached_items():
    engine = _engine({}, [("Acme", 1, "Platform"), ("Acme", 2, "Mobile"), ("Acme", 3, "Platform")])
    engine.manager = None

    assert engine.projects("Acme") == ["Platform", "Mobile"]
    assert [b[0] for b in engine.boards()] == ["Acme · Platform", "Acme · Mobile"]


def test_the_work_item_picker_lists_one_projects_items():
    engine = _engine({"Acme": ["Platform", "Mobile"]},
                     [("Acme", 1, "Platform"), ("Acme", 2, "Mobile")])

    assert [o["id"] for o in engine.get_work_item_options("Acme", "Mobile")] == [2]
    assert [o["id"] for o in engine.get_work_item_options("Acme")] == [2, 1]


def test_each_connection_learns_where_its_cached_items_live():
    engine = _engine({"Acme": ["Platform", "Mobile"], "Beta": ["Ops"]},
                     [("Acme", 1, "Platform"), ("Acme", 2, "Mobile"), ("Beta", 3, "Ops")])

    engine._remember_projects()

    assert engine.manager.clients["Acme"]._project_of == {1: "Platform", 2: "Mobile"}
    assert engine.manager.clients["Beta"]._project_of == {}  # one project: nothing to learn


def test_an_item_cached_without_a_project_counts_as_the_main_ones():
    engine = _engine({"Acme": ["Platform", "Mobile"]}, [("Acme", 1, None), ("Acme", 2, "Mobile")])

    assert [o["id"] for o in engine.get_work_item_options("Acme", "Platform")] == [1]
    assert [o["id"] for o in engine.get_work_item_options("Acme", "Mobile")] == [2]


async def test_a_project_with_nothing_cached_has_its_customer_fetched_in_full_once():
    """The incremental sync only asks for items above the customer's highest
    cached id — a project linked later would keep its older items hidden."""
    import pandas as pd

    engine = _engine({"Acme": ["Platform", "Mobile"], "Beta": ["Ops"]},
                     [("Acme", 1, "Platform"), ("Beta", 2, "Ops")])
    asked = []

    def fetch(max_ids=None, changed_dates=None):
        asked.append(dict(max_ids or {}))
        return True, pd.DataFrame()

    class QueryEngine:
        async def function_db(self, name, *args, **kwargs):
            if name == "get_devops_watermarks":
                return pd.DataFrame({"customer_name": ["Acme", "Beta"], "max_id": [1, 2],
                                     "max_changed_date": ["2026-09-01T00:00:00"] * 2})
            return engine.df

    async def loaded():
        pass

    engine.manager.get_epics_feature_df = fetch
    engine.query_engine, engine.log, engine.load_df = QueryEngine(), _log, loaded
    engine._fully_fetched = set()

    await engine._update_devops_locked(incremental=True)
    await engine._update_devops_locked(incremental=True)

    assert asked == [{"Beta": 2}, {"Acme": 1, "Beta": 2}]  # Acme in full (Mobile), then as usual


def test_a_board_that_cant_be_found_caches_no_columns_not_the_message():
    """A project on another process (Basic has an Issues board, no Stories):
    the lookup's message must not become the columns — the board drew one
    per letter."""
    from collections import defaultdict
    from types import SimpleNamespace

    from src.ui.work_item_handlers import WorkItemHandlers

    client = SimpleNamespace(
        project_name="Platform",
        get_board_columns_via_team_autodetect=lambda board_type, project=None: (
            False, f"No board '{board_type}' found in any team"))
    manager = SimpleNamespace(_get_client=lambda customer: client)
    engine = SimpleNamespace(manager=manager, columns_cache=defaultdict(dict), preload_started=True)

    handlers = WorkItemHandlers(engine, _log)
    result = handlers.load_board_columns("Acme", "User Story", "Basic", "Acme · Basic")

    assert result == ([], False)
    assert engine.columns_cache["Acme · Basic"]["User Story"] == []
