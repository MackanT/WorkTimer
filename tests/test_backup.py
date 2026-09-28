"""Tests for DB backup: Database.backup_to + services.backups."""

import os
import sqlite3

from src.database import Database
from src.services.backups import (
    backups_dir,
    create_backup,
    list_backups,
    prune_backups,
)


def test_backup_to_produces_a_consistent_readable_copy(tmp_path, null_logger):
    src = str(tmp_path / "src.db")
    db = Database(src, null_logger)
    db.initialize_db()
    db.insert_customer("Acme", "2026-01-01", 100)

    dest = str(tmp_path / "backup.db")
    assert db.backup_to(dest) == dest

    # The backup is an independent, valid SQLite DB carrying the data.
    con = sqlite3.connect(dest)
    names = [
        r[0]
        for r in con.execute(
            "select customer_name from customers where is_current = 1"
        ).fetchall()
    ]
    con.close()
    assert "Acme" in names


def test_backup_to_creates_missing_directory(tmp_path, null_logger):
    db = Database(str(tmp_path / "src.db"), null_logger)
    db.initialize_db()
    dest = tmp_path / "nested" / "deep" / "backup.db"
    db.backup_to(str(dest))
    assert dest.exists()


def test_prune_backups_keeps_only_newest(tmp_path):
    files = []
    for i in range(5):
        f = tmp_path / f"worktimer_2026-01-0{i + 1}_000000.db"
        f.write_bytes(b"x")
        os.utime(f, (1000 + i, 1000 + i))  # later i == newer
        files.append(f)
    # An unrelated file must be left untouched.
    (tmp_path / "keep_me.txt").write_text("hi")

    prune_backups(tmp_path, keep=2)

    remaining = sorted(p.name for p in tmp_path.glob("worktimer_*.db"))
    assert remaining == [
        "worktimer_2026-01-04_000000.db",
        "worktimer_2026-01-05_000000.db",
    ]
    assert (tmp_path / "keep_me.txt").exists()


# ── one folder for every entry point (regression, 5.1.2) ────────────────────
# Settings saved one level above the database — under Docker that is the
# container's own filesystem, so every rebuild deleted those backups — while
# the command palette saved next to it.


def test_backups_live_next_to_the_database(tmp_path):
    db_file = tmp_path / "data" / "worktimer.db"
    assert backups_dir(str(db_file)) == (tmp_path / "data" / "backups").resolve()


def test_create_backup_writes_into_the_data_folder_and_keeps_ten(tmp_path, null_logger):
    data = tmp_path / "data"
    data.mkdir()
    db_file = str(data / "worktimer.db")
    db = Database(db_file, null_logger)
    db.initialize_db()
    folder = data / "backups"
    folder.mkdir()
    for i in range(12):
        f = folder / f"worktimer_2026-01-{i + 1:02d}_000000.db"
        f.write_bytes(b"x")
        os.utime(f, (1000 + i, 1000 + i))

    dest = create_backup(db, db_file)
    db.close()

    assert dest.parent == folder.resolve()
    assert dest.read_bytes()[:15] == b"SQLite format 3"
    assert len(list(folder.glob("worktimer_*.db"))) == 10
    assert list_backups(db_file)[0].name == dest.name
    assert not (tmp_path / "backups").exists()


def test_backups_from_the_old_folder_are_moved_in(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    db_file = str(data / "worktimer.db")
    legacy = tmp_path / "backups"
    legacy.mkdir()
    (legacy / "worktimer_2026-08-01_120000.db").write_bytes(b"old")
    (legacy / "unrelated.txt").write_text("hi")

    names = [f.name for f in list_backups(db_file)]

    assert names == ["worktimer_2026-08-01_120000.db"]
    assert (data / "backups" / "worktimer_2026-08-01_120000.db").read_bytes() == b"old"
    assert not (legacy / "worktimer_2026-08-01_120000.db").exists()
    assert (legacy / "unrelated.txt").exists()


# ── Postgres exports share the folder (v6) ──────────────────────────────────


def test_the_folder_lists_and_prunes_both_kinds_of_backup(tmp_path):
    data = tmp_path / "data"
    folder = data / "backups"
    folder.mkdir(parents=True)
    names = ["worktimer_2026-01-01_000000.db", "worktimer_2026-01-02_000000.json.gz",
             "worktimer_2026-01-03_000000.db", "worktimer_2026-01-04_000000.json.gz"]
    for i, name in enumerate(names):
        (folder / name).write_bytes(b"x")
        os.utime(folder / name, (1000 + i, 1000 + i))

    assert [f.name for f in list_backups(str(data / "worktimer.db"))] == names[::-1]
    prune_backups(folder, keep=3)
    assert sorted(f.name for f in folder.iterdir()) == names[1:]


def test_create_backup_names_the_file_by_the_backend(tmp_path):
    class Export:
        BACKUP_SUFFIX = ".json.gz"

        def backup_to(self, dest):
            open(dest, "wb").close()

    dest = create_backup(Export(), str(tmp_path / "worktimer.db"))

    assert dest.name.startswith("worktimer_") and dest.name.endswith(".json.gz")
    assert list_backups(str(tmp_path / "worktimer.db")) == [dest]


# ── one folder per user (v6 Phase 6) ────────────────────────────────────────


class _UserExport:
    BACKUP_SUFFIX = ".json.gz"

    def __init__(self, user_key):
        self.user_key = user_key

    def backup_to(self, dest):
        open(dest, "wb").close()


def test_each_user_backs_up_into_their_own_folder(tmp_path):
    db_file = str(tmp_path / "data" / "worktimer.db")

    ada = create_backup(_UserExport(2), db_file)
    local = create_backup(_UserExport(1), db_file)

    assert ada.parent == (tmp_path / "data" / "users" / "2" / "backups").resolve()
    assert local.parent == (tmp_path / "data" / "backups").resolve()
    assert list_backups(db_file, 2) == [ada]
    assert list_backups(db_file, 3) == []
    assert list_backups(db_file) == [local]


def test_only_the_single_user_install_adopts_old_backups(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    legacy = tmp_path / "backups"
    legacy.mkdir()
    (legacy / "worktimer_2026-08-01_120000.db").write_bytes(b"old")

    assert list_backups(str(data / "worktimer.db"), 2) == []
    assert (legacy / "worktimer_2026-08-01_120000.db").exists()
