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
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from nicegui import background_tasks
from nicegui.storage import Storage
from nicegui.testing import User

from src import globals as wt_globals
from src.core import app as core_app
from src.database import Database
from src.pages import root
from src.services import update_checker

# One event loop for the module, as in production: the app keeps a module-level
# asyncio.Lock (core/app.py _global_tracker_init_lock) bound to the first loop
# that uses it, so a fresh loop per test fails with "bound to a different
# event loop" — a harness artifact, not an app bug.
pytestmark = [pytest.mark.module_under_test(root), pytest.mark.asyncio(loop_scope="module")]

ROOT = Path(__file__).resolve().parents[1]
REAL_DB = (ROOT / "data" / "worktimer.db").resolve()
REAL_STORAGE = (ROOT / ".nicegui").resolve()

PAGES = {  # path -> text proving the page rendered seeded data (None: build check only)
    "/time": "Acme",
    "/tasks": "Write report",
    "/query_editor": "hours by customer",
    "/reports": None,
    "/board": None,
    "/notepad": None,
    "/log": None,
    "/info": None,
    "/settings": None,
}


def _seed(path: Path) -> None:
    """Customers (one with a raise, one disabled), projects (one disabled),
    completed entries across two months, a running timer, a bonus, tasks, a
    saved query and cached work items."""
    lg = logging.getLogger("smoke.seed")
    lg.handlers = [logging.NullHandler()]
    lg.propagate = False
    db = Database(str(path), lg)
    db.initialize_db()
    db.insert_bonus("2026-01-01", 10)
    db.insert_customer("Acme", "2026-01-01", 1000, tracker_project="PLAT",
                       expected_work_pct=50, color="#e11d48")
    db.insert_customer("Beta", "2026-01-01", 850, expected_work_pct=30, color="#0ea5e9")
    db.insert_customer("Gamma", "2026-01-01", 700)
    for customer, project in [("Acme", "Build"), ("Acme", "Support"), ("Beta", "Ops"),
                              ("Beta", "Old"), ("Gamma", "Misc")]:
        db.insert_project(customer, project)

    def ids(customer, project):
        df = db.get_data_input_list()
        row = df[(df.customer_name == customer) & (df.project_name == project)
                 & (df.c_current == 1)].iloc[0]
        return int(row.customer_id), int(row.project_id)

    now = datetime.now()
    for days, customer, project, hours, git_id in [
        (40, "Acme", "Build", 3, 101), (33, "Acme", "Support", 1.5, None),
        (25, "Beta", "Ops", 4, 202), (12, "Acme", "Build", 2.5, 101),
        (5, "Beta", "Ops", 2, None), (2, "Gamma", "Misc", 1, None),
    ]:
        start = (now - timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)
        db.insert_manual_time_row(*ids(customer, project), f"{start:%Y-%m-%d %H:%M}",
                                  f"{start + timedelta(hours=hours):%Y-%m-%d %H:%M}", git_id=git_id)
    db.insert_customer("Acme", f"{now - timedelta(days=10):%Y-%m-%d}", 1150)  # a raise
    db.insert_timer_start_row(*ids("Beta", "Ops"), f"{now - timedelta(hours=1):%Y-%m-%d %H:%M}")
    db.disable_project("Beta", "Old")
    db.disable_customer("Gamma")
    db.insert_task("Write report", priority="High", due_date=f"{now + timedelta(days=3):%Y-%m-%d}",
                   customer_name="Acme", project_name="Build")
    db.insert_task("Fix login", priority="Critical", customer_name="Beta", project_name="Ops")
    db.insert_saved_query("hours by customer",
                          "select customer_name, sum(total_time) as h from time group by customer_name")
    db.update_devops_data(pd.DataFrame([
        {"customer_name": "Acme", "type": "User Story", "id": 101, "title": "Login flow",
         "state": "Active", "changed_date": "2026-09-01T10:00:00"},
        {"customer_name": "Acme", "type": "Task", "id": 102, "title": "Session timeout",
         "state": "New", "parent_id": 101, "changed_date": "2026-09-20T10:00:00"},
    ]), mode="append")
    db.close()


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("smoke") / "worktimer.db"
    _seed(path)
    yield path
    # Close the app's shared connection so the temp file can be removed.
    for key in [k for k in wt_globals._shared_databases if Path(k).resolve() == path.resolve()]:
        wt_globals._shared_databases.pop(key).close()


@pytest.fixture(autouse=True)
def isolated_app(seeded_db, monkeypatch):
    # Autouse, so this runs before NiceGUI's own fixtures reset — and clear —
    # storage.
    assert Storage.path.resolve() != REAL_STORAGE, (
        "NiceGUI storage points at the real .nicegui/ — its test fixtures would "
        "delete it. The root conftest.py must set NICEGUI_STORAGE_PATH first.")
    monkeypatch.setenv("DB_NAME", str(seeded_db))
    monkeypatch.setattr(core_app, "_config_loader", None)  # re-read DB_NAME
    monkeypatch.setattr(update_checker, "_fetch_latest_blocking", update_checker._current_version)

    async def offline(self):
        return False  # skips tracker initialisation, which would need network

    monkeypatch.setattr(core_app.AppCore, "_check_internet", offline)
    yield
    opened = {Path(key).resolve() for key in wt_globals._shared_databases}
    assert REAL_DB not in opened, "a smoke test opened the real data/worktimer.db"


async def _page_built():
    """Every page is `async def`, so ui.sub_pages builds it in a background
    task that can outlive user.open(). Wait for it to finish, then yield once
    so NiceGUI's done-callback logs any exception — which the user fixture
    turns into a failure."""
    for _ in range(100):
        pending = [t for t in background_tasks.running_tasks
                   if t.get_name().startswith("building sub_page") and not t.done()]
        if not pending:
            break
        await asyncio.wait(pending, timeout=0.1)
    else:
        raise AssertionError("sub page still building after 10 s")
    await asyncio.sleep(0)


@pytest.mark.parametrize("path", list(PAGES))
async def test_page_renders_without_errors(user: User, path):
    await user.open(path)
    await _page_built()
    if PAGES[path]:
        await user.should_see(PAGES[path])
