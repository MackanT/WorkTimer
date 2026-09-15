"""Tests for the per-customer fields (expected %, colour) and the 5.0.5
retirement of billing_round_minutes."""

import sqlite3

from src.database import Database


def _row(path):
    con = sqlite3.connect(path)
    r = con.execute(
        "SELECT expected_work_pct, color "
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
        expected_work_pct=50, color="#38bdf8",
    )
    assert _row(path) == (50, "#38bdf8")


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
    db.update_customer("Acme", "Acme", color="#222222")
    exp, col = _row(path)
    assert exp == 50            # untouched (None arg)
    assert col == "#222222"


def test_billing_round_minutes_column_dropped_on_startup(tmp_path, null_logger):
    """A pre-5.0.5 database carries customers.billing_round_minutes; the
    startup migration must drop it (and not re-add it via the schema
    auto-migration)."""
    path = str(tmp_path / "c.db")
    db = Database(path, null_logger)
    db.initialize_db()

    # Simulate the legacy schema: re-add the column with a value in it.
    con = sqlite3.connect(path)
    con.execute("alter table customers add column billing_round_minutes integer")
    con.commit()
    con.close()

    db2 = Database(path, null_logger)
    db2.initialize_db()

    con = sqlite3.connect(path)
    cols = [r[1] for r in con.execute("pragma table_info(customers)").fetchall()]
    con.close()
    assert "billing_round_minutes" not in cols
