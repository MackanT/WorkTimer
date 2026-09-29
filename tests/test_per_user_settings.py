"""Each user's own settings (v6 Phase 6, slice 3): what Settings writes lives
in the user's folder — config/ itself for user 1, data/users/<key>/config/
for everyone else — while the shipped files, the templates and the theme stay
shared. Browser-side preferences get the user's own keys."""

from pathlib import Path

import pytest
import yaml

from src.config import ConfigLoader
from src.core import app as core_app
from src.pages import settings
from src.tracker_defaults import load_tracker_defaults, save_tracker_defaults
from src.user_paths import pref_key

CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def data(tmp_path, monkeypatch):
    """data/ (the database's folder) in a temp dir, as DB_NAME points there."""
    monkeypatch.setenv("DB_NAME", str(tmp_path / "worktimer.db"))
    monkeypatch.delenv("WORKTIMER_SETTINGS_DIR", raising=False)
    return tmp_path


def test_user_1_writes_to_config_and_everyone_else_to_their_own_folder(data):
    local = ConfigLoader(str(CONFIG), user_key=1)
    ada = ConfigLoader(str(CONFIG), user_key=2)

    assert local.user_folder == CONFIG
    assert ada.user_folder == data / "users" / "2" / "config"
    for name in ConfigLoader.USER_FILES:
        assert ada.user_path(name) == ada.user_folder / name
    for shared in ("config_ui.yml", "config_ui_styles.yml", "config_theme.yml", "config_notepad.yml"):
        assert ada.user_path(shared) == CONFIG / shared  # shipped, or the install's


def test_a_users_time_settings_are_theirs_alone(data):
    shipped = (yaml.safe_load((CONFIG / "config_ui.yml").read_text(encoding="utf-8"))
               .get("time_settings") or {})
    ada = ConfigLoader(str(CONFIG), user_key=2)
    ada.user_folder.mkdir(parents=True)
    (ada.user_folder / "time_settings.yml").write_text("rounding_minutes: 45\n", encoding="utf-8")
    bob = ConfigLoader(str(CONFIG), user_key=3)

    assert ada.load_all()["ui"].time_settings["rounding_minutes"] == 45
    # Bob has written nothing: the shipped defaults — never user 1's
    # config/time_settings.yml, whatever that says
    assert bob.load_all()["ui"].time_settings.get("rounding_minutes") == shipped.get("rounding_minutes")
    assert (bob.user_folder / "devops_contacts.yml").exists()  # from the shared template


def test_settings_writes_into_the_users_folder(data):
    class Core:
        config_loader = ConfigLoader(str(CONFIG), user_key=2)

    path = settings._config_path(Core, "time_settings.yml")
    settings._save_yaml(path, {"rounding_minutes": 30})

    assert path == data / "users" / "2" / "config" / "time_settings.yml"
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"rounding_minutes": 30}
    assert settings._template_path(Core, "devops_tags.yml") == CONFIG / "devops_tags.yml.template"


def test_tracker_defaults_are_per_user(data):
    ada, bob = ConfigLoader(str(CONFIG), user_key=2), ConfigLoader(str(CONFIG), user_key=3)

    save_tracker_defaults(ada.user_folder, {"Ops": {"*": {"area_path": "Ops\\Team"}}})

    assert load_tracker_defaults(ada.user_folder) == {"Ops": {"*": {"area_path": "Ops\\Team"}}}
    assert load_tracker_defaults(bob.user_folder) == {}


def test_each_user_gets_their_own_loader(data, monkeypatch):
    monkeypatch.setattr(core_app, "_config_loaders", {})

    ada, bob = core_app.get_config_loader(2), core_app.get_config_loader(3)

    assert ada is core_app.get_config_loader(2)
    assert ada is not bob and (ada.user_key, bob.user_key) == (2, 3)


def test_preferences_are_keyed_by_user():
    assert pref_key(1, "report_customers") == "report_customers"  # saved ones survive
    assert pref_key(2, "report_customers") != pref_key(3, "report_customers")
    assert pref_key(2, "report_customers") != "report_customers"


def test_the_settings_folder_can_live_outside_the_image(data, monkeypatch):
    """Under Docker, config/ is the image's — replaced on every build — so
    WORKTIMER_SETTINGS_DIR moves what is written into the mounted data/."""
    monkeypatch.setenv("WORKTIMER_SETTINGS_DIR", str(data / "config"))
    local = ConfigLoader(str(CONFIG), user_key=1)
    ada = ConfigLoader(str(CONFIG), user_key=2)

    assert local.user_path("time_settings.yml") == data / "config" / "time_settings.yml"
    assert local.user_path("config_theme.yml") == data / "config" / "config_theme.yml"
    assert local.user_path("config_ui.yml") == CONFIG / "config_ui.yml"  # what ships stays
    assert ada.user_path("time_settings.yml") == data / "users" / "2" / "config" / "time_settings.yml"
    assert ada.user_path("config_theme.yml") == data / "config" / "config_theme.yml"  # the install's
    local.load_all()
    assert (data / "config" / "config_theme.yml").exists()  # from the shipped template
