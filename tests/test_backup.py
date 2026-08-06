"""Tests for DB backup: Database.backup_to + add_data._prune_backups."""

import os
import sqlite3

from src.database import Database
from src.pages.settings import _prune_backups


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

    _prune_backups(tmp_path, keep=2)

    remaining = sorted(p.name for p in tmp_path.glob("worktimer_*.db"))
    assert remaining == [
        "worktimer_2026-01-04_000000.db",
        "worktimer_2026-01-05_000000.db",
    ]
    assert (tmp_path / "keep_me.txt").exists()
