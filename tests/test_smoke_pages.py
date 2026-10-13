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
