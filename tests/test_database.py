"""Regression tests for src/database.py — the bulk of the audit fixes live here."""

import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.database import Database


# ── Schema init & migration (§7.5) ──────────────────────────────────────────


def test_fresh_db_has_no_schema_drift(db):
    """A freshly initialized DB must validate clean (triggers come from one source)."""
    res = db.validate_and_migrate_schema(auto_migrate=False)
    assert not res["missing_columns"]
    assert not res["missing_triggers"]
    assert not res["outdated_triggers"]
    assert not res["errors"]


def test_all_expected_triggers_present(db):
    names = {
        r[0]
        for r in db.conn.execute(
            "select name from sqlite_master where type='trigger'"
        ).fetchall()
    }
    assert {
        "trigger_time_after_update",
        "trigger_time_insert_row",
        "trigger_time_update_row",
    } <= names


def test_outdated_trigger_is_recreated_then_stable(db):
    """Plant a stale trigger; auto-migrate must recreate it and then report clean."""
    db.execute_query("drop trigger if exists trigger_time_insert_row")
    db.execute_query(
        """
        create trigger trigger_time_insert_row
        after insert on time
        for each row
        begin
            update time
            set bonus = ifnull((
                    select bonus_percent from bonus
                    where current_date between start_date and ifnull(end_date, '2099-12-31')
                ), 0)
            where time_id = new.time_id;
        end;
        """
    )
    res = db.validate_and_migrate_schema(auto_migrate=True)
    assert res["outdated_triggers"] == ["trigger_time_insert_row"]
    assert any(m.get("action") == "recreated" for m in res["applied_migrations"])

    # Running again must find no drift (normalization has to be stable).
    res2 = db.validate_and_migrate_schema(auto_migrate=False)
    assert not res2["outdated_triggers"]
    assert not res2["missing_triggers"]


def test_legacy_devops_table_gets_missing_columns(tmp_path, null_logger):
    """An old bare devops table must gain the columns added in later versions."""
    path = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(path)
    raw.execute(
        "create table devops (customer_name text, type text, id integer, "
        "title text, state text, parent_id integer)"
    )
    raw.commit()
    raw.close()

    db = Database(path, null_logger)
    db.initialize_db()
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(devops)").fetchall()}
    assert {
        "board_column",
        "board_column_done",
        "assigned_to",
        "changed_date",
        "priority",
    } <= cols
    db.close()


def test_tasks_table_has_no_foreign_keys(db):
    """Old FKs referenced non-unique columns; they were dropped."""
    ddl = db.fetch_query(
        "select sql from sqlite_master where type='table' and name='tasks'"
    ).iloc[0]["sql"]
    assert "foreign key" not in ddl.lower()


def test_busy_timeout_is_set(db):
    assert db.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_dates_horizon_extends_when_close(tmp_path, null_logger):
    """The dates table auto-extends so reports don't go blank past its end."""
    path = str(tmp_path / "dates.db")
    db = Database(path, null_logger)
    db.initialize_db()
    # Fresh horizon is 2030-12-31 (today + 1y is still < 2030).
    assert db.fetch_query("select max(date) as m from dates").iloc[0]["m"] == "2030-12-31"

    # Simulate an aged DB whose horizon is within a year of today, then re-init.
    horizon_cut = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
    db.execute_query("delete from dates where date > ?", (horizon_cut,))
    db.initialize_db()
    new_max = db.fetch_query("select max(date) as m from dates").iloc[0]["m"]
    assert new_max > "2030-01-01"
    # No duplicate date_keys introduced by the extension.
    counts = db.fetch_query(
        "select count(*) c, count(distinct date_key) d from dates"
    ).iloc[0]
    assert int(counts["c"]) == int(counts["d"])
    db.close()


# ── insert_task tuple contract (§1.1) ────────────────────────────────────────


def test_insert_task_returns_three_tuple(db):
    ok, msg, task = db.insert_task(title="Test task")
    assert ok is True
    assert isinstance(task, dict) and task["title"] == "Test task"


def test_delete_task_removes_it(db):
    _, _, task = db.insert_task(title="ToDelete")
    tid = task["task_id"]
    ok, _msg = db.delete_task(tid)
    assert ok is True
    remaining = db.fetch_query(
        "select count(*) c from tasks where task_id = ?", (tid,)
    )
    assert int(remaining.iloc[0]["c"]) == 0


def test_delete_missing_task_reports_failure(db):
    ok, _msg = db.delete_task(999999)
    assert ok is False


# ── Backdated bonus uses the entry date, not today (§7.6) ────────────────────


def _seed_customer_project(db, wage=100):
    db.execute_query(
        "insert into customers (customer_name, start_date, wage, is_current) "
        "values ('C', '2025-01-01', ?, 1)",
        (wage,),
    )
    cid = int(db.fetch_query("select customer_id from customers").iloc[0]["customer_id"])
    db.execute_query(
        "insert into projects (customer_id, project_name, is_current) values (?, 'P', 1)",
        (cid,),
    )
    pid = int(db.fetch_query("select project_id from projects").iloc[0]["project_id"])
    return cid, pid


def test_backdated_entry_gets_historic_bonus_rate(db):
    cid, pid = _seed_customer_project(db)
    db.insert_bonus("2025-01-01", 10)  # 10% through 2025
    db.insert_bonus("2026-01-01", 20)  # 20% from 2026

    db.insert_manual_time_row(cid, pid, "2025-06-01 10:00", "2025-06-01 12:00")
    db.insert_manual_time_row(cid, pid, "2026-06-01 10:00", "2026-06-01 12:00")

    rows = db.fetch_query("select date_key, bonus from time order by date_key")
    assert abs(rows.iloc[0]["bonus"] - 0.10) < 1e-9  # 2025 entry -> 10%
    assert abs(rows.iloc[1]["bonus"] - 0.20) < 1e-9  # 2026 entry -> 20%


def test_manual_time_row_fires_both_triggers(db):
    cid, pid = _seed_customer_project(db)
    db.insert_manual_time_row(cid, pid, "2026-08-01 10:00", "2026-08-01 12:00")
    row = db.fetch_query(
        "select total_time, customer_name, project_name from time"
    ).iloc[0]
    assert abs(row["total_time"] - 2.0) < 1e-3
    assert row["customer_name"] == "C" and row["project_name"] == "P"


# ── DevOps write-through cache is customer-scoped (§1.8) ──────────────────────


def test_devops_field_update_is_customer_scoped(db):
    df = pd.DataFrame(
        [
            {"customer_name": "A", "type": "User Story", "id": 1, "title": "a",
             "state": "New", "parent_id": None, "board_column": "New",
             "board_column_done": 0, "assigned_to": "", "changed_date": "", "priority": 2},
            {"customer_name": "B", "type": "User Story", "id": 1, "title": "b",
             "state": "New", "parent_id": None, "board_column": "New",
             "board_column_done": 0, "assigned_to": "", "changed_date": "", "priority": 2},
        ]
    )
    db.update_devops_data(df, mode="replace")
    db.update_devops_item_fields(1, {"board_column": "Done"}, customer_name="A")

    res = db.fetch_query(
        "select customer_name, board_column from devops order by customer_name"
    )
    assert res.iloc[0]["board_column"] == "Done"  # A moved
    assert res.iloc[1]["board_column"] == "New"  # B (same id) untouched


# ── Partial updates don't wipe omitted fields (§9) ───────────────────────────


def test_update_customer_leaves_omitted_credentials(db):
    db.execute_query(
        "insert into customers (customer_name, start_date, wage, org_url, pat_token, is_current) "
        "values ('C', '2025-01-01', 100, 'org', 'tok', 1)"
    )
    db.update_customer("C", "C2")  # no org/pat -> unchanged
    row = db.fetch_query(
        "select customer_name, org_url, pat_token from customers"
    ).iloc[0]
    assert row["customer_name"] == "C2"
    assert row["org_url"] == "org" and row["pat_token"] == "tok"

    db.update_customer("C2", "C2", org_url="", pat_token="")  # explicit clear
    row = db.fetch_query("select org_url, pat_token from customers").iloc[0]
    assert row["org_url"] == "" and row["pat_token"] == ""


def test_update_project_leaves_omitted_git_id(db):
    cid, pid = _seed_customer_project(db)
    db.execute_query("update projects set git_id = 42 where project_id = ?", (pid,))
    db.update_project("C", "P", "P2")  # git_id omitted -> unchanged
    row = db.fetch_query("select project_name, git_id from projects").iloc[0]
    assert row["project_name"] == "P2" and int(row["git_id"]) == 42

    db.update_project("C", "P2", "P2", new_git_id=7)
    assert int(db.fetch_query("select git_id from projects").iloc[0]["git_id"]) == 7


# ── SQL identifier / table validation (security surface) ─────────────────────


def test_validate_identifier_accepts_and_rejects(db):
    assert db._validate_identifier("customer_id") == "customer_id"
    for bad in ("1bad", "a-b", "drop table x", "", "a;b"):
        with pytest.raises(ValueError):
            db._validate_identifier(bad)


def test_validate_query_edit_table_whitelist(db):
    for good in ("time", "customers", "projects"):
        assert db._validate_query_edit_table(good) == good
    for bad in ("devops", "bonus", "sqlite_master"):
        with pytest.raises(ValueError):
            db._validate_query_edit_table(bad)


def test_update_data_from_query_rejects_bad_column(db):
    with pytest.raises(ValueError):
        db.update_data_from_query(
            table_name="time",
            pk_data=("time_id", 1),
            **{"evil-col": "x"},
        )
