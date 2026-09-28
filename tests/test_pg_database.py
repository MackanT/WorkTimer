"""The Postgres data layer (src/pg_database.py, v6 Phase 2) — what is new or
different on Postgres, beyond the characterisation tests it shares with
SQLite: UTC storage with local dating, the write path's snapshot and rounding
rules, the query editor's row edit (plan step 2), soft delete, the work-item
cache, and one API instance per user.
"""

import pandas as pd
import pytest

psycopg = pytest.importorskip("psycopg")

from src.pg_database import PgDatabase  # noqa: E402

pytestmark = [pytest.mark.backends("postgres"), pytest.mark.postgres]


def _acme(db, *projects):
    db.insert_customer("Acme", "2026-01-01", 1000)
    for p in projects or ("Build",):
        db.insert_project("Acme", p)


def _pid(db, project, customer="Acme"):
    df = db.get_data_input_list()
    row = df[(df.customer_name == customer) & (df.project_name == project)]
    return int(row.iloc[0].customer_id), int(row.iloc[0].project_id)


def _entries(db):
    return db.fetch_query(
        """
        select key_time_entry as id, fk_project, started_at, ended_at, fk_date,
               duration_hours, wage_snapshot, cost, comment, bk_work_item, deleted_at
        from time_entries order by key_time_entry
        """).to_dict("records")


# ── time: stored in UTC, dated and shown in the user's zone ────────────────


def test_an_entry_after_local_midnight_is_dated_by_its_local_day(db):
    """v6_plan §4: 00:30 in Stockholm is 22:30 UTC the previous evening — the
    entry belongs to the local day."""
    _acme(db)
    db.insert_manual_time_row(*_pid(db, "Build"), "2026-07-01 00:30", "2026-07-01 01:30")

    [e] = _entries(db)
    assert e["fk_date"] == 20260701
    assert e["started_at"].isoformat() == "2026-06-30T22:30:00+00:00"
    [shown] = db.get_completed_entries(*_pid(db, "Build"), 20260701, 20260701)["start_time"]
    assert shown == "2026-07-01 00:30:00"


@pytest.mark.parametrize("day, hours", [
    ("2026-10-25", 4.0),  # clocks go back at 03:00 — 01:00→04:00 is four real hours
    ("2026-03-29", 2.0),  # clocks go forward at 02:00 — two real hours
])
def test_durations_across_a_dst_change_are_real_hours(db, day, hours):
    """Naive local times (5.x) would bill three hours both nights."""
    _acme(db)
    db.insert_manual_time_row(*_pid(db, "Build"), f"{day} 01:00", f"{day} 04:00")

    [e] = _entries(db)
    assert e["duration_hours"] == pytest.approx(hours)
    assert e["cost"] == pytest.approx(1000 * hours)


def test_times_follow_the_users_timezone(db):
    db.execute_query("update users set timezone = 'America/New_York'")
    _acme(db)
    db.insert_manual_time_row(*_pid(db, "Build"), "2026-07-01 09:00", "2026-07-01 10:00")

    [e] = _entries(db)
    assert e["started_at"].isoformat() == "2026-07-01T13:00:00+00:00"
    [shown] = db.get_completed_entries(*_pid(db, "Build"), 20260701, 20260701)["start_time"]
    assert shown == "2026-07-01 09:00:00"


# ── the write path ──────────────────────────────────────────────────────────


def test_cost_is_computed_from_the_exact_duration_and_rounded_once(db):
    """20 minutes at 1000/h: 333.333… → 333.33, not 0.33 h × 1000 = 330."""
    _acme(db)
    db.insert_manual_time_row(*_pid(db, "Build"), "2026-09-01 09:00", "2026-09-01 09:20")

    [e] = db.fetch_query("select cost, duration_hours from time_entries").to_dict("records")
    assert e["cost"] == 333.33
    assert e["duration_hours"] == pytest.approx(0.3333)


def test_an_entry_before_the_first_wage_period_uses_the_first_wage(db):
    _acme(db)
    db.insert_manual_time_row(*_pid(db, "Build"), "2025-06-02 09:00", "2025-06-02 10:00")

    assert _entries(db)[0]["wage_snapshot"] == 1000


def test_a_raise_must_start_after_the_current_wage_began(db, pg_schema_db):
    _acme(db)
    with pytest.raises(ValueError, match="must start after 2026-01-01"):
        db.insert_customer("Acme", "2026-01-01", 1200)
    with psycopg.connect(pg_schema_db) as admin:
        wages = admin.execute("select wage, valid_from, valid_to from customer_wages").fetchall()
    assert [(w, str(f), t) for w, f, t in wages] == [(1000, "2026-01-01", None)]


def test_unrelated_edits_never_re_price_history(db, pg_schema_db):
    """A wage correction after the fact reaches an entry only when the entry
    itself moves to another day — not through a comment edit."""
    _acme(db)
    db.insert_manual_time_row(*_pid(db, "Build"), "2026-09-01 09:00", "2026-09-01 10:00")
    with psycopg.connect(pg_schema_db) as admin:
        admin.execute("update customer_wages set wage = 1100")
    [e] = _entries(db)

    db.update_time_entry(e["id"], comment="noted")
    assert _entries(db)[0]["cost"] == 1000

    db.update_time_entry(e["id"], start_time="2026-09-02 09:00", end_time="2026-09-02 10:00")
    assert (_entries(db)[0]["wage_snapshot"], _entries(db)[0]["cost"]) == (1100, 1100)


def test_deleting_an_entry_keeps_it_as_history(db):
    _acme(db)
    db.insert_manual_time_row(*_pid(db, "Build"), "2026-09-01 09:00", "2026-09-01 10:00")
    db.delete_time_entry(_entries(db)[0]["id"])

    [e] = _entries(db)
    assert e["deleted_at"] is not None
    assert db.report_totals("2026-09-01", "2026-09-30").iloc[0]["n"] == 0


def test_discarding_a_running_timer(db):
    _acme(db)
    cid, pid = _pid(db, "Build")
    db.insert_timer_start_row(cid, pid, "2026-09-01 09:00")

    db.delete_time_row(cid, pid)

    assert db.get_running_timers().empty
    assert _entries(db)[0]["deleted_at"] is not None


# ── the query editor's row edit (plan step 2) ───────────────────────────────


def _row_save(db, key, **fields):
    db.update_data_from_query(table_name="time", pk_data=("time_id", key), **fields)


def test_a_row_edit_re_prices_the_entry(db):
    """Without SQLite's trigger, a plain UPDATE of the times would leave the
    cost stale — a silently wrong invoice. The row edit uses the write path."""
    _acme(db, "Build", "Support")
    db.insert_manual_time_row(*_pid(db, "Build"), "2026-09-01 09:00", "2026-09-01 10:00")
    key = _entries(db)[0]["id"]

    row = db.get_query_edit_data("time", key).iloc[0]
    assert (row["start_time"], row["end_time"], row["project_name"]) == (
        "2026-09-01 09:00:00", "2026-09-01 10:00:00", "Build")

    _row_save(db, key, project_name="Support", start_time="2026-09-01 09:00:00",
              end_time="2026-09-01 12:30:00", comment="fixed", git_id=0)

    [e] = _entries(db)
    assert (e["duration_hours"], e["cost"]) == (3.5, 3500)
    assert (e["fk_project"], e["comment"], e["bk_work_item"]) == (_pid(db, "Support")[1], "fixed", None)


def test_a_row_edit_naming_an_unknown_project_changes_nothing(db):
    _acme(db)
    db.insert_manual_time_row(*_pid(db, "Build"), "2026-09-01 09:00", "2026-09-01 10:00")
    before = _entries(db)

    with pytest.raises(ValueError, match="No project named 'Nope'"):
        _row_save(db, before[0]["id"], project_name="Nope", end_time="2026-09-01 12:00")

    assert _entries(db) == before


def test_customer_and_project_row_edits_touch_only_their_fields(db):
    _acme(db)
    cid, pid = _pid(db, "Build")

    db.update_data_from_query(table_name="customers", pk_data=("customer_id", cid),
                              expected_work_pct=60, color="#abcdef")
    db.update_data_from_query(table_name="projects", pk_data=("project_id", pid), git_id=4242)

    assert db.get_query_edit_data("customers", cid).to_dict("records") == [
        {"expected_work_pct": 60.0, "color": "#abcdef"}]
    assert db.get_query_edit_data("projects", pid).iloc[0]["git_id"] == 4242
    with pytest.raises(ValueError, match="Invalid column"):
        db.update_data_from_query(table_name="customers", pk_data=("customer_id", cid),
                                  customer_name="Renamed")
    with pytest.raises(ValueError, match="not editable"):
        db.get_query_edit_data("trackers", 1)


# ── the work-item cache ─────────────────────────────────────────────────────


def _items(**rows):
    return pd.DataFrame([{"customer_name": c, "id": i, "title": t, "state": "New",
                          "board_column_done": 0, "changed_date": "2026-09-01T10:00:00Z"}
                         for c, i, t in rows.values()])


def test_syncs_upsert_and_replace_the_cache(db):
    for name in ("Acme", "Beta"):
        db.insert_customer(name, "2026-01-01", 1000)
    db.update_devops_data(_items(a=("Acme", 5, "a"), b=("Beta", 5, "b"),
                                 ghost=("Gone Ltd", 9, "x")), mode="replace")
    db.update_devops_data(_items(a=("Acme", 5, "a v2"), c=("Acme", 6, "c")), mode="merge")

    df = db.get_visible_devops_items()
    assert list(zip(df["customer_name"], df["id"], df["title"])) == [
        ("Acme", 5, "a v2"), ("Acme", 6, "c"), ("Beta", 5, "b")]  # the unknown customer: skipped

    db.update_devops_data(_items(b=("Beta", 7, "only")), mode="replace")
    assert db.get_visible_devops_items()["id"].tolist() == [7]


def test_a_write_through_hits_only_the_named_customers_item(db):
    """Work-item ids are unique per tracker organisation, not across customers."""
    for name in ("Acme", "Beta"):
        db.insert_customer(name, "2026-01-01", 1000)
    db.update_devops_data(_items(a=("Acme", 5, "a"), b=("Beta", 5, "b")), mode="replace")

    db.update_devops_item_fields(5, {"state": "Done", "board_column_done": 1, "id": 99},
                                 customer_name="Acme")

    df = db.get_visible_devops_items()
    assert list(zip(df["customer_name"], df["state"], df["board_column_done"])) == [
        ("Acme", "Done", 1), ("Beta", "New", 0)]


# ── tasks and trackers ──────────────────────────────────────────────────────


def test_a_task_for_an_unknown_customer_is_refused(db):
    ok, message, task = db.insert_task("Orphan", customer_name="Nobody")

    assert (ok, task) == (False, None)
    assert "No customer named 'Nobody'" in message


def test_tracker_tokens_round_trip_through_the_key_in_secrets_dir(db, tmp_path):
    db.insert_tracker("Ops", "devops", org_url="ops", pat_token="secret-pat")

    assert db.get_trackers().iloc[0]["pat_token"].startswith("enc:")
    assert db.get_tracker_credentials("Ops") == ("devops", "ops", "secret-pat")
    assert (tmp_path / ".pat_key").exists()


# ── one instance per user ───────────────────────────────────────────────────


def test_each_user_sees_only_their_own_data(db, pg_schema_db, tmp_path):
    with psycopg.connect(pg_schema_db) as admin:
        user2 = admin.execute("insert into users (bk_user) values ('second') "
                              "returning key_user").fetchone()[0]
    other = PgDatabase(db.pools, db.log_engine, user_key=user2, secrets_dir=str(tmp_path))
    _acme(db)
    db.insert_manual_time_row(*_pid(db, "Build"), "2026-09-01 09:00", "2026-09-01 10:00")

    assert other.get_customer_ui_list("20260101", "20261231").empty
    assert other.report_totals("2026-01-01", "2026-12-31").iloc[0]["n"] == 0
    other.insert_customer("Acme", "2026-01-01", 500)  # the same name is free for them
    assert db.get_data_input_list()["wage"].tolist() == [1000]
    assert other.get_data_input_list()["wage"].tolist() == [500]
