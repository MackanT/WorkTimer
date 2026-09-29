"""A 5.x install in one zip (src/import_bundle.py): what is taken from it,
what is refused, and how its notes and settings land without overwriting."""

import zipfile

import pytest

from src import import_bundle

DB = b"SQLite format 3\x00the-rest"


def _zip(path, members: dict):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return path


def test_only_what_worktimer_knows_is_taken(tmp_path):
    bundle_zip = _zip(tmp_path / "wt.zip", {
        "data/worktimer.db": DB,
        "data/.pat_key": b"key",
        "data/notes/plan.md": b"# Plan",
        "data/notes/notes_meta.json": b"{}",
        "data/notes/plan_assets/img_1.png": b"png",
        "data/notes/plan_assets/evil.svg": b"<svg onload=alert(1)/>",  # not a raster image
        "data/notes/sub/deep.md": b"too deep",
        "data/notes/readme.txt": b"not a note",
        "data/backups/worktimer_old.db": b"old",
        "config/time_settings.yml": b"rounding_minutes: 15\n",
        "config/devops_contacts.yml": b"customers: {}\n",
        "config/config_theme.yml": b"colors: {}\n",  # the user's own palette
        "config/config_notepad.yml": b"x: 1\n",  # the install's, not a user's
        "../escape.md": b"out",
        "/abs/notes/x.md": b"abs",
        "__MACOSX/data/notes/._plan.md": b"meta",
    })

    with import_bundle.opened(bundle_zip) as bundle:
        assert bundle.db_path.read_bytes() == DB
        assert bundle.pat_key_path.read_bytes() == b"key"
        folder = bundle.db_path.parent
        assert bundle.notes == {"plan.md": b"# Plan", "notes_meta.json": b"{}",
                                "plan_assets/img_1.png": b"png"}
        assert bundle.settings == {"time_settings.yml": b"rounding_minutes: 15\n",
                                   "devops_contacts.yml": b"customers: {}\n",
                                   "config_theme.yml": b"colors: {}\n"}
    assert not folder.exists()  # the temp copies are gone


def test_a_zip_of_the_folders_contents_works_too(tmp_path):
    bundle_zip = _zip(tmp_path / "wt.zip", {"worktimer.db": DB, "notes/a.md": b"# A"})

    with import_bundle.opened(bundle_zip) as bundle:
        assert bundle.notes == {"a.md": b"# A"}
        assert bundle.pat_key_path is None and bundle.settings == {}


def test_a_zip_without_a_database_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no worktimer.db"):
        with import_bundle.opened(_zip(tmp_path / "wt.zip", {"notes/a.md": b"# A"})):
            pass


def test_the_size_and_file_count_are_capped(tmp_path, monkeypatch):
    bundle_zip = _zip(tmp_path / "wt.zip", {"worktimer.db": DB, "notes/a.md": b"x" * 1000})
    monkeypatch.setattr(import_bundle, "MAX_UNPACKED_BYTES", 500)
    with pytest.raises(ValueError, match="300 MB"):
        with import_bundle.opened(bundle_zip):
            pass
    monkeypatch.setattr(import_bundle, "MAX_UNPACKED_BYTES", 10**9)
    monkeypatch.setattr(import_bundle, "MAX_MEMBERS", 1)
    with pytest.raises(ValueError, match="more than 1 files"):
        with import_bundle.opened(bundle_zip):
            pass


def test_notes_land_and_earlier_ones_are_kept_aside(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "mine.md").write_text("# Mine")

    moved = import_bundle.place_notes({"plan.md": b"# Plan", "plan_assets/i.png": b"png"}, notes)

    assert moved is not None and (moved / "mine.md").read_text() == "# Mine"
    assert (notes / "plan.md").read_bytes() == b"# Plan"
    assert (notes / "plan_assets" / "i.png").read_bytes() == b"png"
    assert not (notes / "mine.md").exists()
    assert import_bundle.place_notes({"b.md": b"# B"}, tmp_path / "fresh") is None


def test_settings_land_and_earlier_files_are_kept(tmp_path):
    (tmp_path / "time_settings.yml").write_text("rounding_minutes: 5\n")

    names = import_bundle.place_settings(
        {"time_settings.yml": b"rounding_minutes: 15\n", "config_ui.yml": b"not mine"}, tmp_path)

    assert names == ["time_settings.yml"]
    assert (tmp_path / "time_settings.yml").read_text() == "rounding_minutes: 15\n"
    [kept] = tmp_path.glob("before-import-*/time_settings.yml")
    assert kept.read_text() == "rounding_minutes: 5\n"
    assert not (tmp_path / "config_ui.yml").exists()
