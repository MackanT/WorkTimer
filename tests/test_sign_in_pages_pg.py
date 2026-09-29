"""Hosted mode (v6 Phase 6): the app behind Cloudflare Access, on Postgres.

Pages and endpoints are opened as simulated users carrying Access tokens
(tests/_access.py): no valid sign-in, no app; each signed-in user acts as
their own user — created on the first sign-in — and sees only their own data.
"""

import dataclasses
import logging

import pytest

psycopg = pytest.importorskip("psycopg")
from nicegui.testing import User  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402

from _access import ADA, BOB, CONFIG, OTHER_KEY, token, verifier  # noqa: E402
from _smoke import page_built  # noqa: E402
from src import auth, http_safety  # noqa: E402
from src import globals as wt_globals  # noqa: E402
from src.auth import ACCESS_HEADER, AuthConfig, Identity  # noqa: E402
from src.core import app as core_app  # noqa: E402
from src.pages import notepad, root  # noqa: E402
from src.pg_connection import ConfigError, PgConfig, Pools  # noqa: E402
from src.pg_database import PgDatabase  # noqa: E402
from src.services import update_checker  # noqa: E402
from src.ui import work_item_forms  # noqa: E402

pytestmark = [pytest.mark.module_under_test(root), pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.postgres]


@pytest.fixture(scope="module")
def app_url(pg_schema_db_module, pg_logins):
    url = make_conninfo(pg_schema_db_module, user="worktimer_app",
                        password=pg_logins["worktimer_app"])
    yield url
    for key in [k for k in wt_globals._shared_databases if isinstance(k, tuple) and k[0] == url]:
        wt_globals._shared_databases.pop(key)
    if url in wt_globals._shared_pools:
        wt_globals._shared_pools.pop(url).close()


@pytest.fixture(scope="module")
def ada_key(app_url, tmp_path_factory):
    """Ada has signed in before and has a customer; Bob never has."""
    quiet = logging.getLogger("signin.seed")
    quiet.handlers = [logging.NullHandler()]
    quiet.propagate = False
    pools = Pools(PgConfig(app_url), max_size=1)
    key = pools.sign_in(ADA, "ada@example.com", "Ada")
    db = PgDatabase(pools, quiet, user_key=key, secrets_dir=str(tmp_path_factory.mktemp("seed")))
    db.initialize_db()
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    pools.close()
    return key


@pytest.fixture(autouse=True)
def hosted(app_url, ada_key, tmp_path_factory, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", app_url)
    monkeypatch.setenv("DB_NAME", str(tmp_path_factory.mktemp("data") / "worktimer.db"))
    monkeypatch.setattr(auth, "_config", CONFIG)
    monkeypatch.setattr(auth, "_verifier", verifier())
    monkeypatch.setattr(notepad, "DATA_DIR", tmp_path_factory.mktemp("notes-data"))
    monkeypatch.setattr(core_app, "_config_loaders", {})
    monkeypatch.setattr(update_checker, "_fetch_latest_blocking", update_checker._current_version)

    async def offline(self):
        return False

    monkeypatch.setattr(core_app.AppCore, "_check_internet", offline)


@pytest.fixture
def endpoints(user: User) -> User:
    """NiceGUI's test reset drops the routes modules add at import; put back
    the endpoints under test (after `user` has reset the app)."""
    from nicegui import app

    app.get("/staged_image/{token}")(work_item_forms.staged_image)
    app.post("/upload_devops_image")(work_item_forms.upload_devops_image)
    app.get("/devops_attachment")(work_item_forms.devops_attachment)
    app.post("/upload_image")(notepad.upload_image)
    app.get("/notes_assets/{folder}/{name}")(notepad.notes_asset)
    http_safety.install(app)
    return user


def _sign_in(user: User, sub: str, **claims) -> User:
    user.http_client.headers[ACCESS_HEADER] = token(sub=sub, email=f"{sub[:4]}@example.com", **claims)
    return user


async def test_without_a_sign_in_the_app_stays_shut(user: User):
    await user.open("/time")
    await user.should_see("Not signed in")
    await user.should_not_see("Acme")


async def test_a_forged_token_is_refused(user: User):
    _sign_in(user, ADA, key=OTHER_KEY)
    await user.open("/time")
    await user.should_see("Not signed in")
    await user.should_not_see("Acme")


async def test_each_user_sees_only_their_own_data(create_user, ada_key, pg_schema_db_module):
    ada = _sign_in(create_user(), ADA)
    await ada.open("/time")
    await page_built()
    await ada.should_see("Acme")

    bob = _sign_in(create_user(), BOB)
    await bob.open("/time")
    await page_built()
    await bob.should_not_see("Acme")

    with psycopg.connect(pg_schema_db_module) as admin:
        [(bob_key,)] = admin.execute("select key_user from users where bk_user = %s", (BOB,)).fetchall()
    cores = {core.user_key: core for core in core_app._app_cores.values()}
    assert {ada_key, bob_key} <= set(cores)  # a first sign-in created Bob
    assert cores[bob_key].query_engine.db.user_key == bob_key
    assert cores[ada_key].query_engine.db is not cores[bob_key].query_engine.db


async def test_the_endpoints_need_a_sign_in_and_serve_only_the_users_own(endpoints: User, ada_key):
    user = endpoints
    http = user.http_client
    url = work_item_forms.stage_image("paste.png", b"\x89PNG-bytes", ada_key)

    assert (await http.get(url)).status_code == 401
    assert (await http.get("/devops_attachment", params={"url": "https://x"})).status_code == 401
    assert (await http.post("/upload_devops_image", data={"customer": "Acme"},
                            files={"file": ("a.png", b"x")})).status_code == 401
    _sign_in(user, BOB)
    assert (await http.get(url)).status_code == 404  # Ada's, not Bob's
    _sign_in(user, ADA)
    response = await http.get(url)
    assert response.status_code == 200 and response.content == b"\x89PNG-bytes"


async def test_single_user_mode_refuses_a_database_people_signed_in_to(app_url, monkeypatch):
    monkeypatch.setattr(auth, "_config", AuthConfig())
    monkeypatch.setattr(wt_globals, "_shared_pools", {})
    with pytest.raises(ConfigError, match="signed-in user"):
        wt_globals._shared_pools_for(app_url)
    with pytest.raises(ConfigError, match="signed-in user"):  # endpoints too: never user 1
        wt_globals.user_key_for(None)
    assert wt_globals._shared_pools == {}


PNG = b"\x89PNG\r\n\x1a\n-pixels"


async def test_notes_images_are_each_users_own(endpoints: User, ada_key):
    http = endpoints.http_client

    def upload(name="shot.png", content=PNG):
        return http.post("/upload_image", data={"note": "plan.md"}, files={"file": (name, content)})

    assert (await upload()).status_code == 401
    _sign_in(endpoints, ADA)
    path = (await upload()).json()["path"]
    assert path.startswith("/notes_assets/plan_assets/")
    assert (notepad.get_notes_dir(ada_key) / "plan_assets").is_dir()
    response = await http.get(path)
    assert response.status_code == 200 and response.content == PNG
    assert "error" in (await upload("x.svg", b"<svg onload=alert(1)/>")).json()
    (notepad.get_notes_dir(ada_key) / "plan_assets" / "notes.md").write_text("# private")
    assert (await http.get("/notes_assets/plan_assets/notes.md")).status_code == 404

    _sign_in(endpoints, BOB)
    assert (await http.get(path)).status_code == 404  # not in Bob's notes
    http.headers.pop(ACCESS_HEADER)
    assert (await http.get(path)).status_code == 401


async def test_the_app_palette_is_the_installs_when_people_sign_in(user: User):
    _sign_in(user, ADA)
    await user.open("/settings")
    await page_built()
    await user.should_see("Set for everyone on this server", retries=20)
    await user.should_not_see("Save Theme")
    await user.should_see("Query editor skin")  # each user's own


async def test_the_owners_first_sign_in_lands_in_the_single_user_data(monkeypatch):
    """Going online: WORKTIMER_OWNER_EMAIL's first sign-in takes over user 1.
    Last in the module — it takes user 1 over."""
    monkeypatch.setattr(auth, "_config", dataclasses.replace(CONFIG, owner_email="owner@example.com"))

    assert wt_globals.user_key_for(Identity("not-the-owner", "x@example.com")) != 1
    assert wt_globals.user_key_for(Identity("owner-sub", "Owner@Example.com")) == 1
    assert wt_globals.user_key_for(Identity("owner-sub", "owner@example.com")) == 1


async def test_a_colleague_imports_their_zipped_data_folder(user: User, tmp_path, pg_schema_db_module):
    """Onboarding through the Settings card: a zip of the 5.x data folder with
    its config folder — data, tracker token, notes and settings, each into the
    colleague's own account and folders."""
    import io
    import zipfile

    from nicegui import ui
    from starlette.datastructures import UploadFile

    from src.database import Database

    v5_dir = tmp_path / "v5" / "data"
    v5_dir.mkdir(parents=True)
    quiet = logging.getLogger("signin.v5")
    quiet.handlers = [logging.NullHandler()]
    quiet.propagate = False
    v5 = Database(str(v5_dir / "worktimer.db"), quiet)
    v5.initialize_db()
    v5.insert_tracker("Carol DevOps", "devops", org_url="carol-org", pat_token="carols-pat")
    v5.insert_customer("Carol AB", "2026-01-01", 900, tracker_name="Carol DevOps")
    v5.insert_project("Carol AB", "Build")
    row = v5.get_data_input_list().query("project_name == 'Build'").iloc[0]
    v5.insert_manual_time_row(int(row.customer_id), int(row.project_id),
                              "2026-09-01 09:00", "2026-09-01 11:00")
    v5.close()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.write(v5_dir / "worktimer.db", "data/worktimer.db")
        zf.write(v5_dir / ".pat_key", "data/.pat_key")
        zf.writestr("data/notes/plan.md", "# Carol's plan")
        zf.writestr("data/notes/plan_assets/img_1.png", b"png")
        zf.writestr("config/time_settings.yml", "rounding_minutes: 15\n")

    _sign_in(user, "carol-sub-0001")
    await user.open("/settings")
    await page_built()
    user.find(ui.upload).elements.pop().handle_uploads(
        [UploadFile(io.BytesIO(buffer.getvalue()), filename="carol-data.zip")])
    await user.should_see("5.x data folder (zip)", retries=100)
    user.find(kind=ui.button, content="Import").click()
    await user.should_see("every customer's numbers match", retries=100)  # the notification

    with psycopg.connect(pg_schema_db_module) as admin:
        [(carol,)] = admin.execute(
            "select key_user from users where bk_user = 'carol-sub-0001'").fetchall()
        assert admin.execute("select count(*) from time_entries where fk_user = %s",
                             (carol,)).fetchone() == (1,)
    carol_db = next(c.query_engine.db for c in core_app._app_cores.values() if c.user_key == carol)
    assert carol_db.get_tracker_credentials("Carol DevOps") == ("devops", "carol-org", "carols-pat")
    notes = notepad.get_notes_dir(carol)
    assert (notes / "plan.md").read_text(encoding="utf-8") == "# Carol's plan"
    assert (notes / "plan_assets" / "img_1.png").read_bytes() == b"png"
    config = core_app.get_config_loader(carol).user_folder
    assert (config / "time_settings.yml").read_text(encoding="utf-8") == "rounding_minutes: 15\n"



async def test_another_site_cannot_spend_the_sign_in(endpoints: User):
    """The security review: a cross-site POST carries the Access cookie, so
    it is refused before any endpoint runs; pages can't be framed."""
    http = endpoints.http_client
    _sign_in(endpoints, ADA)
    files = {"file": ("shot.png", PNG)}

    cross = await http.post("/upload_image", data={"note": "plan.md"}, files=files,
                            headers={"Sec-Fetch-Site": "cross-site"})
    same = await http.post("/upload_image", data={"note": "plan.md"}, files=files,
                           headers={"Sec-Fetch-Site": "same-origin"})

    assert cross.status_code == 403
    assert same.status_code == 200 and "path" in same.json()
    page = await http.get("/time")
    assert page.headers["x-frame-options"] == "DENY"
