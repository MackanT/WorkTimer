"""Tracker token-expiry: the trackers.token_expires column, its CRUD
plumbing, and the warning classifier behind the once-a-day startup toast."""

import sqlite3
from datetime import date

import pytest

from src.database import Database
from src.helpers import token_expiry_level


TODAY = date(2026, 9, 15)


def test_expiry_level_classification():
    assert token_expiry_level("2026-09-10", TODAY) == ("expired", -5)
    assert token_expiry_level("2026-09-15", TODAY) == ("critical", 0)
    assert token_expiry_level("2026-09-22", TODAY) == ("critical", 7)
    assert token_expiry_level("2026-09-23", TODAY) == ("warning", 8)
    assert token_expiry_level("2026-10-15", TODAY) == ("warning", 30)
    assert token_expiry_level("2026-10-16", TODAY) == ("ok", 31)


def test_expiry_level_bad_input_returns_none():
    assert token_expiry_level("", TODAY) is None
    assert token_expiry_level(None, TODAY) is None
    assert token_expiry_level("not-a-date", TODAY) is None


def _expiry(path, name):
    con = sqlite3.connect(path)
    val = con.execute(
        "select token_expires from trackers where tracker_name = ?", (name,)
    ).fetchone()[0]
    con.close()
    return val


def test_insert_and_update_tracker_expiry_roundtrip(tmp_path, null_logger):
    path = str(tmp_path / "t.db")
    db = Database(path, null_logger)
    db.initialize_db()

    db.insert_tracker(
        "Acme (devops)", integration_type="devops",
        org_url="acme", pat_token="secret", token_expires="2027-01-31",
    )
    assert _expiry(path, "Acme (devops)") == "2027-01-31"

    # Blank = unchanged (matching the credential fields' contract).
    db.update_tracker("Acme (devops)", org_url="acme2", token_expires="")
    assert _expiry(path, "Acme (devops)") == "2027-01-31"

    db.update_tracker("Acme (devops)", token_expires="2027-06-30")
    assert _expiry(path, "Acme (devops)") == "2027-06-30"


def test_insert_tracker_without_expiry_stores_null(tmp_path, null_logger):
    path = str(tmp_path / "t.db")
    db = Database(path, null_logger)
    db.initialize_db()
    db.insert_tracker("Acme (devops)", org_url="acme", pat_token="secret")
    assert _expiry(path, "Acme (devops)") is None


def test_invalid_expiry_date_raises(tmp_path, null_logger):
    path = str(tmp_path / "t.db")
    db = Database(path, null_logger)
    db.initialize_db()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        db.insert_tracker(
            "Acme (devops)", org_url="acme", pat_token="secret",
            token_expires="31/01/2027",
        )


def test_token_expires_column_added_on_startup(tmp_path, null_logger):
    """A pre-5.1.0 trackers table lacks token_expires; the schema
    auto-migration must add it."""
    path = str(tmp_path / "t.db")
    db = Database(path, null_logger)
    db.initialize_db()

    con = sqlite3.connect(path)
    con.execute("alter table trackers drop column token_expires")
    con.commit()
    con.close()

    db2 = Database(path, null_logger)
    db2.initialize_db()

    con = sqlite3.connect(path)
    cols = [r[1] for r in con.execute("pragma table_info(trackers)").fetchall()]
    con.close()
    assert "token_expires" in cols
