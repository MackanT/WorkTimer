"""Tests for the new per-customer fields (expected %, billing rounding, colour)."""

import sqlite3

from src.database import Database


def _row(path):
    con = sqlite3.connect(path)
    r = con.execute(
        "SELECT expected_work_pct, billing_round_minutes, color "
        "FROM customers WHERE is_current = 1"
    ).fetchone()
    con.close()
    return r


def test_insert_customer_persists_new_fields(tmp_path, null_logger):
    path = str(tmp_path / "c.db")
    db = Database(path, null_logger)
    db.initialize_db()
    db.insert_customer(
        "Acme", "2026-01-01", 100,
        expected_work_pct=50, billing_round_minutes=15, color="#38bdf8",
    )
    assert _row(path) == (50, 15, "#38bdf8")


def test_insert_customer_defaults_and_stores_integration_type(tmp_path, null_logger):
    path = str(tmp_path / "c.db")
    db = Database(path, null_logger)
    db.initialize_db()
    db.insert_customer("Acme", "2026-01-01", 100)  # no tracker given
    db.insert_customer("Jira Co", "2026-01-01", 100, integration_type="jira")

    con = sqlite3.connect(path)
    rows = dict(con.execute(
        "select customer_name, integration_type from customers where is_current = 1"
    ).fetchall())
    con.close()
    assert rows == {"Acme": "devops", "Jira Co": "jira"}


def test_update_customer_changes_integration_type_only_when_given(tmp_path, null_logger):
    path = str(tmp_path / "c.db")
    db = Database(path, null_logger)
    db.initialize_db()
    db.insert_customer("Acme", "2026-01-01", 100)
    db.update_customer("Acme", "Acme", color="#111111")  # no tracker → unchanged
    db.update_customer("Acme", "Acme", integration_type="jira")

    con = sqlite3.connect(path)
    val = con.execute(
        "select integration_type from customers where is_current = 1"
    ).fetchone()[0]
    con.close()
    assert val == "jira"


def test_update_customer_updates_new_fields_and_leaves_others(tmp_path, null_logger):
    path = str(tmp_path / "c.db")
    db = Database(path, null_logger)
    db.initialize_db()
    db.insert_customer("Acme", "2026-01-01", 100, expected_work_pct=50, color="#111111")
    # 0 minutes → NULL (use global); colour changed; expected untouched.
    db.update_customer(
        "Acme", "Acme",
        billing_round_minutes=0, color="#222222",
    )
    exp, rnd, col = _row(path)
    assert exp == 50            # untouched (None arg)
    assert rnd is None          # 0 → NULL
    assert col == "#222222"
