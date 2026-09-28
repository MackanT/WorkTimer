"""Page smoke test on Postgres (v6 Phase 2): every page, opened as a simulated
user, with DATABASE_URL set — the switch that puts the app on PgDatabase —
against a seeded throwaway database. The user fixture fails a test on any
ERROR log, so a page calling something the Postgres data layer lacks, or
getting a shape it can't render, fails here.

The seed data and the page list are shared with tests/test_smoke_pages.py.
"""

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
    if url in wt_globals._shared_databases:
        wt_globals._shared_databases.pop(url).close()


@pytest.fixture(autouse=True)
def isolated_app(app_url, tmp_path_factory, monkeypatch):
    assert Storage.path.resolve() != REAL_STORAGE, (
        "NiceGUI storage points at the real .nicegui/ — its test fixtures would "
        "delete it. The root conftest.py must set NICEGUI_STORAGE_PATH first.")
    monkeypatch.setenv("DATABASE_URL", app_url)
    # data/ for the PAT key and backups: a throwaway folder, not the real one.
    monkeypatch.setenv("DB_NAME", str(tmp_path_factory.mktemp("data") / "worktimer.db"))
    monkeypatch.setattr(core_app, "_config_loader", None)
    monkeypatch.setattr(update_checker, "_fetch_latest_blocking", update_checker._current_version)

    async def offline(self):
        return False  # skips tracker initialisation, which would need network

    monkeypatch.setattr(core_app.AppCore, "_check_internet", offline)
    yield
    # The page ran on Postgres: the app opened the data layer for DATABASE_URL.
    assert isinstance(wt_globals._shared_databases.get(app_url), PgDatabase)


@pytest.mark.parametrize("path", list(PAGES))
async def test_page_renders_on_postgres(user: User, path):
    await user.open(path)
    await page_built()
    if PAGES[path]:
        await user.should_see(PAGES[path])


async def test_reports_show_each_currency_on_its_own(user: User, app_url, tmp_path):
    """v6_plan §4: a EUR customer's amount stands beside SEK's, never added
    to it. Last in the module — it adds to the shared seed."""
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
