"""Page smoke test on Postgres (v6 Phase 2): every page, opened as a simulated
user, with DATABASE_URL set — the switch that puts the app on PgDatabase —
against a seeded throwaway database. The user fixture fails a test on any
ERROR log, so a page calling something the Postgres data layer lacks, or
getting a shape it can't render, fails here.

The seed data and the page list are shared with tests/test_smoke_pages.py.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
from nicegui.storage import Storage  # noqa: E402
from nicegui.testing import User  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402

from src import globals as wt_globals  # noqa: E402
from src.core import app as core_app  # noqa: E402
from src.pages import root  # noqa: E402
from src.pg_connection import PgConfig, Pools  # noqa: E402
from src.pg_database import PgDatabase  # noqa: E402
from src.services import update_checker  # noqa: E402

from _smoke import PAGES, page_built, seed  # noqa: E402

pytestmark = [pytest.mark.module_under_test(root), pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.postgres]

REAL_STORAGE = (Path(__file__).resolve().parents[1] / ".nicegui").resolve()


@pytest.fixture(scope="module")
def app_url(pg_schema_db_module, pg_logins, tmp_path_factory):
    """The app role's URL for a seeded database; the app's shared connection
    pool is closed when the module is done."""
    url = make_conninfo(pg_schema_db_module, user="worktimer_app",
                        password=pg_logins["worktimer_app"])
    quiet = logging.getLogger("smoke.seed")
    quiet.handlers = [logging.NullHandler()]
    quiet.propagate = False
    pools = Pools(PgConfig(url), max_size=1)
    seed(PgDatabase(pools, quiet, secrets_dir=str(tmp_path_factory.mktemp("seed"))))
    pools.close()
    yield url
    for key in [k for k in wt_globals._shared_databases if isinstance(k, tuple) and k[0] == url]:
        wt_globals._shared_databases.pop(key)
    if url in wt_globals._shared_pools:
        wt_globals._shared_pools.pop(url).close()


@pytest.fixture(autouse=True)
def isolated_app(app_url, tmp_path_factory, monkeypatch):
    assert Storage.path.resolve() != REAL_STORAGE, (
        "NiceGUI storage points at the real .nicegui/ — its test fixtures would "
        "delete it. The root conftest.py must set NICEGUI_STORAGE_PATH first.")
    monkeypatch.setenv("DATABASE_URL", app_url)
    # data/ for the PAT key and backups: a throwaway folder, not the real one.
    monkeypatch.setenv("DB_NAME", str(tmp_path_factory.mktemp("data") / "worktimer.db"))
    monkeypatch.setattr(core_app, "_config_loaders", {})
    monkeypatch.setattr(update_checker, "_fetch_latest_blocking", update_checker._current_version)

    async def offline(self):
        return False  # skips tracker initialisation, which would need network

    monkeypatch.setattr(core_app.AppCore, "_check_internet", offline)
    yield
    # The page ran on Postgres: the app opened the data layer for DATABASE_URL.
    assert isinstance(wt_globals._shared_databases.get((app_url, 1)), PgDatabase)


@pytest.mark.parametrize("path", list(PAGES))
async def test_page_renders_on_postgres(user: User, path):
    await user.open(path)
    await page_built()
    if PAGES[path]:
        await user.should_see(PAGES[path])


async def test_reports_show_each_currency_on_its_own(user: User, app_url, tmp_path):
    """v6_plan §4: a EUR customer's amount stands beside SEK's, never added
    to it. After the page tests — it adds to the shared seed."""
    quiet = logging.getLogger("smoke.seed")
    pools = Pools(PgConfig(app_url), max_size=1)
    db = PgDatabase(pools, quiet, secrets_dir=str(tmp_path))
    db.insert_customer("Euro GmbH", "2026-01-01", 100, currency="EUR")
    db.insert_project("Euro GmbH", "Audit")
    row = db.get_data_input_list().query("project_name == 'Audit'").iloc[0]
    today = datetime.now().strftime("%Y-%m-%d")
    db.insert_manual_time_row(int(row.customer_id), int(row.project_id),
                              f"{today} 00:00", f"{today} 00:30")
    pools.close()

    await user.open("/reports")
    await page_built()
    await user.should_see("50 EUR")


async def test_the_update_tab_previews_a_rate_change_then_re_prices(user: User, app_url, tmp_path):
    """The Customers dialog's Update tab: a changed hourly rate is previewed
    with the logged time it re-prices, and saving asks first. After the page
    tests — it adds to the shared seed."""
    from nicegui import ui
    from nicegui.testing.user_interaction import UserInteraction

    from src.pages.add_data import open_entity_dialog

    pools = Pools(PgConfig(app_url), max_size=1)
    db = PgDatabase(pools, logging.getLogger("smoke.seed"), secrets_dir=str(tmp_path))
    db.insert_customer("Rate AB", "2026-01-01", 1000)
    db.insert_project("Rate AB", "Work")
    row = db.get_data_input_list().query("project_name == 'Work'").iloc[0]
    db.insert_manual_time_row(int(row.customer_id), int(row.project_id),
                              "2026-03-02 09:00", "2026-03-02 11:00")

    await user.open("/time")  # not "/": its redirect builds the page in a second client
    await page_built()
    core = core_app._app_cores[user.client.id]
    with user.client:
        await open_entity_dialog(core, "customer", "update", presets={"customer_name": "Rate AB"})
        panel = next(e for e in user.client.elements.values()
                     if isinstance(e, ui.tab_panel) and e.props.get("name") == "update")
        fields = {e.props.get("label"): e for e in panel.descendants()
                  if isinstance(e, (ui.input, ui.number))}
        save = next(e for e in panel.descendants() if isinstance(e, ui.button) and e.text == "Update")
    await user.should_see("Hourly rates", retries=50)
    await user.should_see("Change the rate or its date to see the result here.")
    with user.client:
        fields["Rate from"].value = "2026-03-01"
        fields["Hourly rate"].value = 1500
    await user.should_see("+1 000.00", retries=50)  # the re-priced period's change
    await user.should_see("1 entry")

    UserInteraction(user, {save}, None).click()
    await user.should_see("Change the hourly rate of Rate AB?", retries=50)
    await user.should_see("1, dated 2026-03-02")
    user.find(kind=ui.button, content="Change rate").click()
    await user.should_see("customer Rate AB updated!", retries=50)

    cost = db.fetch_query("select te.cost from time_entries te join projects p "
                          "on p.key_project = te.fk_project where p.project_name = 'Work'")
    assert cost["cost"].tolist() == [3000]

    # The change's ✕ in the rate table removes it again: back to 1 000.
    with user.client:
        await open_entity_dialog(core, "customer", "update", presets={"customer_name": "Rate AB"})
        panels = [e for e in user.client.elements.values()
                  if isinstance(e, ui.tab_panel) and e.props.get("name") == "update"]
    await user.should_see("Hourly rates", retries=50)
    [remove] = [e for e in max(panels, key=lambda p: p.id).descendants()
                if isinstance(e, ui.button) and e.props.get("icon") == "close"]
    UserInteraction(user, {remove}, None).click()
    await user.should_see("Remove the rate change on 2026-03-01?", retries=50)
    user.find(kind=ui.button, content="Remove").click()
    await user.should_see("Rate change on 2026-03-01 removed", retries=50)
    cost = db.fetch_query("select te.cost from time_entries te join projects p "
                          "on p.key_project = te.fk_project where p.project_name = 'Work'")
    assert cost["cost"].tolist() == [2000]
    pools.close()


async def test_the_tracker_project_follows_the_selected_tracker(user: User, app_url, tmp_path,
                                                               monkeypatch):
    """The Update tab's Tracker project lists the SELECTED tracker's projects —
    also one the customer isn't linked to yet — with the customer's own
    project preselected on its own tracker. After the page tests."""
    from nicegui import ui

    from src.pages import add_data
    from src.pages.add_data import open_entity_dialog

    pools = Pools(PgConfig(app_url), max_size=1)
    db = PgDatabase(pools, logging.getLogger("smoke.seed"), secrets_dir=str(tmp_path))
    db.insert_tracker("Ops DevOps", "devops", org_url="ops", pat_token="pat")
    db.insert_tracker("Dev Jira", "jira", jira_site="https://dev.atlassian.net",
                      jira_email="me@example.com", jira_api_token="tok")
    db.insert_customer("Track AB", "2026-01-01", 1000, tracker_name="Ops DevOps",
                       tracker_project="Platform")
    pools.close()
    projects = {"Ops DevOps": ["Platform", "Mobile"], "Dev Jira": ["DEV", "OPS"]}

    async def listed(core, name):
        return projects[name], None

    monkeypatch.setattr(add_data, "_projects_of_tracker", listed)

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    with user.client:
        await open_entity_dialog(core, "customer", "update", presets={"customer_name": "Track AB"})
        panel = next(e for e in user.client.elements.values()
                     if isinstance(e, ui.tab_panel) and e.props.get("name") == "update")
        selects = {e.props.get("label"): e for e in panel.descendants() if isinstance(e, ui.select)}
    tracker, project = selects["Tracker"], selects["Tracker project"]
    for _ in range(50):
        if project.value == "Platform":
            break
        await asyncio.sleep(0.05)
    assert (project.options, project.value) == (["Platform", "Mobile"], "Platform")

    with user.client:
        tracker.value = "Dev Jira"  # another tracker: its projects, none chosen yet
    for _ in range(50):
        if project.options == ["DEV", "OPS"]:
            break
        await asyncio.sleep(0.05)
    assert (project.options, project.value) == (["DEV", "OPS"], None)


async def test_switching_customer_shows_its_own_tracker_and_project(user: User, app_url, tmp_path,
                                                                    monkeypatch):
    """Without a project list (offline, no token): each customer still shows
    its own tracker and project, and one without a tracker shows none.
    After the page tests."""
    from nicegui import ui

    from src.pages import add_data
    from src.pages.add_data import open_entity_dialog

    pools = Pools(PgConfig(app_url), max_size=1)
    db = PgDatabase(pools, logging.getLogger("smoke.seed"), secrets_dir=str(tmp_path))
    db.insert_tracker("Side DevOps", "devops", org_url="side", pat_token="pat")
    db.insert_tracker("Side Jira", "jira", jira_site="https://side.atlassian.net",
                      jira_email="me@example.com", jira_api_token="tok")
    db.insert_customer("Side AB", "2026-01-01", 1000, tracker_name="Side DevOps",
                       tracker_project="Platform")
    db.insert_customer("Jira AB", "2026-01-01", 1000, tracker_name="Side Jira",
                       tracker_project="DEV")
    db.insert_customer("Plain AB", "2026-01-01", 1000)
    pools.close()

    async def unlisted(core, name):
        return [], "Tracker not reachable: only projects already in use"

    monkeypatch.setattr(add_data, "_projects_of_tracker", unlisted)

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]
    with user.client:
        await open_entity_dialog(core, "customer", "update", presets={"customer_name": "Side AB"})
        panel = next(e for e in user.client.elements.values()
                     if isinstance(e, ui.tab_panel) and e.props.get("name") == "update")
        selects = {e.props.get("label"): e for e in panel.descendants() if isinstance(e, ui.select)}
    customer, tracker, project = selects["Name"], selects["Tracker"], selects["Tracker project"]

    async def shows(expected):
        for _ in range(60):
            if (tracker.value, project.value) == expected:
                return
            await asyncio.sleep(0.05)
        assert (tracker.value, project.value) == expected

    await shows(("Side DevOps", "Platform"))
    for name, expected in [("Jira AB", ("Side Jira", "DEV")), ("Plain AB", (None, None)),
                           ("Side AB", ("Side DevOps", "Platform"))]:
        with user.client:
            customer.value = name
        await shows(expected)


async def test_without_a_token_a_tracker_offers_the_projects_in_use(user: User, app_url, tmp_path):
    """No token stored: the projects listed are those its customers use, and
    the field says so. After the page tests."""
    from src.pages import add_data

    pools = Pools(PgConfig(app_url), max_size=1)
    db = PgDatabase(pools, logging.getLogger("smoke.seed"), secrets_dir=str(tmp_path))
    db.insert_tracker("Bare DevOps", "devops", org_url="bare")
    db.insert_customer("Bare A", "2026-01-01", 1000, tracker_name="Bare DevOps",
                       tracker_project="Beta")
    db.insert_customer("Bare B", "2026-01-01", 1000, tracker_name="Bare DevOps",
                       tracker_project="Alpha")
    db.insert_customer("Bare C", "2026-01-01", 1000, tracker_name="Bare DevOps")
    pools.close()

    await user.open("/time")
    await page_built()
    core = core_app._app_cores[user.client.id]

    projects, note = await add_data._projects_of_tracker(core, "Bare DevOps")

    assert projects == ["Alpha", "Beta"]
    assert note.startswith("No token stored")
