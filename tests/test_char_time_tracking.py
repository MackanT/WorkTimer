"""Characterisation tests: the Time Tracker page's reads, pinned as they behave
in 5.1.x now that they live in the data layer.

Part of the Postgres-port oracle (docs/v6_implementation.md, Phase 0.2).
Everything goes through public ``Database`` methods — no SQL in this file.

Two pinned quirks share one root cause (v6_plan §3, problem 2): a wage
change gives the customer a new ``customer_id``, but completed time entries
keep the old one, while the page always asks with the current id. Phase 2 finds
entries through the project instead, which fixes both — each test says how its
expectation changes, to be applied as a reviewed diff. (A third, the running
timer, was fixed early in 5.1.1.)
"""

from datetime import datetime, timedelta

import pytest

HOURS = 1e-6  # ≈ 3.6 ms


def _hours(value):
    return pytest.approx(value, abs=HOURS)


def _acme(db) -> None:
    """Acme at 1000/h from 2026-01-01, with one project: Build."""
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")


def _ids(db, customer: str, project: str) -> tuple[int, int]:
    """(customer_id, project_id) for the customer's *current* version."""
    df = db.get_data_input_list()
    row = df[
        (df.customer_name == customer)
        & (df.c_current == 1)
        & (df.project_name == project)
    ]
    assert len(row) == 1, f"expected one current row for {customer}/{project}"
    return int(row.iloc[0].customer_id), int(row.iloc[0].project_id)


def _customer_id(db, name: str) -> int:
    df = db.get_current_customers()
    return int(df[df.customer_name == name].iloc[0].customer_id)


def _ago(days: int = 0, hours: float = 0) -> str:
    return (datetime.now() - timedelta(days=days, hours=hours)).strftime("%Y-%m-%d %H:%M")


# ── customers and projects ──────────────────────────────────────────────────


def test_customer_name_by_id(db):
    _acme(db)

    assert db.get_customer_name(_customer_id(db, "Acme")) == "Acme"
    assert db.get_customer_name(999) == ""


def test_current_customers_follow_the_saved_sort_order(db):
    for name in ["Charlie", "Alpha", "Bravo", "Delta"]:
        db.insert_customer(name, "2026-01-01", 1000)
    db.disable_customer("Delta")

    df = db.get_current_customers_in_sort_order()
    assert df["customer_name"].tolist() == ["Alpha", "Bravo", "Charlie"]  # unset → by name
    assert df["so"].tolist() == [999, 999, 999]

    order = [(_customer_id(db, n), n) for n in ["Charlie", "Alpha", "Bravo"]]
    db.save_sort_order(order, {})

    df = db.get_current_customers_in_sort_order()
    assert df["customer_name"].tolist() == ["Charlie", "Alpha", "Bravo"]


def test_current_projects_exclude_disabled_and_are_ordered_by_name(db):
    _acme(db)
    db.insert_project("Acme", "Support")
    db.insert_project("Acme", "Admin")
    db.disable_project("Acme", "Support")

    df = db.get_current_projects_for_customer(_customer_id(db, "Acme"))

    assert df["project_name"].tolist() == ["Admin", "Build"]


def test_customer_project_info(db):
    _acme(db)
    db.insert_project("Acme", "Support", git_id=555)
    db.insert_customer("Beta", "2026-01-01", 800)
    acme, support = _ids(db, "Acme", "Support")

    [info] = db.get_customer_project_info(acme, support).to_dict("records")
    assert (info["customer_name"], info["project_name"], info["git_id"]) == (
        "Acme", "Support", 555)
    # A project that belongs to another customer matches nothing.
    assert db.get_customer_project_info(_customer_id(db, "Beta"), support).empty


def test_logged_project_info_uses_the_names_on_the_entries(db):
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    assert db.get_logged_project_info(cid, pid).empty  # no entries yet

    db.insert_manual_time_row(cid, pid, "2026-09-01 09:00", "2026-09-01 10:00")
    db.update_customer("Acme", "Acme AB")  # renames the entries' names too

    [info] = db.get_logged_project_info(cid, pid).to_dict("records")
    assert (info["customer_name"], info["project_name"]) == ("Acme AB", "Build")


# ── running timers ──────────────────────────────────────────────────────────


def test_running_timers_and_their_names(db):
    _acme(db)
    db.insert_project("Acme", "Support")
    db.insert_customer("Beta", "2026-01-01", 800)
    db.insert_project("Beta", "Ops")
    acme, support = _ids(db, "Acme", "Support")
    beta, ops = _ids(db, "Beta", "Ops")

    db.insert_timer_start_row(beta, ops, "2026-09-01 08:00")
    db.insert_timer_start_row(acme, support, "2026-09-01 09:00")

    running = set(map(tuple, db.get_running_timers()[["customer_id", "project_id"]].values))
    assert running == {(acme, support), (beta, ops)}
    names = db.get_running_timer_names()
    assert list(map(tuple, names.values)) == [("Acme", "Support"), ("Beta", "Ops")]
    [start] = db.get_running_timer_start(acme, support)["start_time"]
    assert start == "2026-09-01 09:00:00"

    db.insert_time_row(acme, support, end_time="2026-09-01 10:00")  # stop it

    assert db.get_running_timer_start(acme, support).empty
    assert db.get_running_timer_names()["customer_name"].tolist() == ["Beta"]


def test_timer_running_across_a_wage_change_follows_the_customer(db):
    """Fixed in 5.1.1 (pinned here as a bug until then). A raise gives the
    customer a new id and the running timer now moves with it, so the time
    tracker — asking with the current id — finds it, and its click stops it
    rather than starting a second timer."""
    _acme(db)
    old_id, pid = _ids(db, "Acme", "Build")
    db.insert_timer_start_row(old_id, pid, "2026-09-01 09:00")

    db.insert_customer("Acme", "2026-09-01", 1200)  # raise → new version
    new_id, _ = _ids(db, "Acme", "Build")

    assert db.get_running_timer_names()["customer_name"].tolist() == ["Acme"]
    assert db.get_running_timer_start(old_id, pid).empty
    [start] = db.get_running_timer_start(new_id, pid)["start_time"]
    assert start == "2026-09-01 09:00:00"

    db.insert_time_row(new_id, pid, end_time="2026-09-01 11:00")  # the tracker's click

    assert db.get_running_timers().empty


# ── "Manage entries" ────────────────────────────────────────────────────────


def test_completed_entries_in_range_newest_first(db):
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-09-01 09:00", "2026-09-01 10:00")
    db.insert_manual_time_row(cid, pid, "2026-09-03 09:00", "2026-09-03 11:00")
    db.insert_manual_time_row(cid, pid, "2026-10-01 09:00", "2026-10-01 10:00")
    db.insert_timer_start_row(cid, pid, "2026-09-05 09:00")  # running: excluded

    df = db.get_completed_entries(cid, pid, 20260901, 20260930)

    assert df["start_time"].tolist() == ["2026-09-03 09:00:00", "2026-09-01 09:00:00"]
    assert df["total_time"].tolist() == [_hours(2.0), _hours(1.0)]
    assert list(df.columns) == ["time_id", "start_time", "end_time", "total_time", "comment"]


def test_completed_entries_before_a_wage_change_are_hidden(db):
    """PINNED QUIRK — a bug; fixed by Phase 2.

    "Manage entries" asks with the current customer id, so an entry logged
    before a raise is missing from the dialog even though it is in range.
    Phase 2 finds entries through the project: expect both entries (2 rows).
    """
    _acme(db)
    old_id, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(old_id, pid, "2026-08-03 09:00", "2026-08-03 11:00")
    db.insert_customer("Acme", "2026-09-01", 1200)
    new_id, _ = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(new_id, pid, "2026-09-02 09:00", "2026-09-02 10:00")

    df = db.get_completed_entries(new_id, pid, 20260801, 20260930)

    assert df["start_time"].tolist() == ["2026-09-02 09:00:00"]


# ── ranges and usage ────────────────────────────────────────────────────────


def test_first_entry_date(db):
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    assert db.get_first_entry_date().iloc[0]["min_date"] is None  # no entries

    db.insert_manual_time_row(cid, pid, "2026-09-03 09:00", "2026-09-03 10:00")
    db.insert_manual_time_row(cid, pid, "2026-08-14 09:00", "2026-08-14 10:00")

    assert db.get_first_entry_date().iloc[0]["min_date"] == "2026-08-14"


def test_recent_project_hours_cover_the_last_60_days(db):
    _acme(db)
    db.insert_project("Acme", "Support")
    cid, build = _ids(db, "Acme", "Build")
    _, support = _ids(db, "Acme", "Support")
    db.insert_manual_time_row(cid, build, _ago(10), _ago(10, -2))  # 2 h, inside
    db.insert_manual_time_row(cid, build, _ago(70), _ago(70, -1))  # outside
    db.insert_manual_time_row(cid, support, _ago(1), _ago(1, -1))  # 1 h, inside
    db.insert_timer_start_row(cid, support, _ago(hours=0.5))  # running, ≈ 0.5 h

    df = db.get_recent_project_hours(cid)
    hours = dict(zip(df["project_id"].astype(int), df["h"]))

    assert hours[build] == _hours(2.0)
    assert hours[support] == pytest.approx(1.5, abs=0.02)


def test_recent_hours_before_a_wage_change_are_not_counted(db):
    """PINNED QUIRK — a bug; fixed by Phase 2.

    "Sort by usage" asks with the current customer id, so usage logged before a
    raise (still inside the 60 days) is ignored. Phase 2 finds entries through
    the project: expect 3.0 hours.
    """
    _acme(db)
    old_id, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(old_id, pid, _ago(20), _ago(20, -2))  # 2 h before the raise
    db.insert_customer("Acme", datetime.now().strftime("%Y-%m-%d"), 1200)
    new_id, _ = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(new_id, pid, _ago(5), _ago(5, -1))  # 1 h after

    df = db.get_recent_project_hours(new_id)

    assert dict(zip(df["project_id"].astype(int), df["h"])) == {pid: _hours(1.0)}
