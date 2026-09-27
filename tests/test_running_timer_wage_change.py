"""Regression (5.1.1): a timer running while its customer's wage changes.

A wage change is an SCD2 update — the customer gets a new customer_id. The
running entry must move with it, or the Time Tracker (which asks with the
current id) can no longer see or stop it: the checkbox shows stopped, ticking
it starts a second timer, and the original runs on.
"""

import pytest


def _ids(db, customer: str, project: str) -> tuple[int, int]:
    """(customer_id, project_id) for the customer's current version."""
    df = db.get_data_input_list()
    row = df[
        (df.customer_name == customer)
        & (df.c_current == 1)
        & (df.project_name == project)
    ]
    assert len(row) == 1
    return int(row.iloc[0].customer_id), int(row.iloc[0].project_id)


def _running(db) -> list[int]:
    """customer_id of every running entry, oldest first."""
    return db.fetch_query(
        "select customer_id from time where end_time is null order by time_id"
    )["customer_id"].astype(int).tolist()


@pytest.fixture
def acme(db):
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    return db


def test_running_timer_follows_a_wage_change(acme):
    db = acme
    old_id, pid = _ids(db, "Acme", "Build")
    db.insert_timer_start_row(old_id, pid, "2026-09-01 09:00")

    db.insert_customer("Acme", "2026-09-01", 1200)  # raise → new customer_id
    new_id, _ = _ids(db, "Acme", "Build")
    assert new_id != old_id
    assert _running(db) == [new_id]

    # The tracker's stop path, with the current id, stops it — no second timer.
    db.insert_time_row(new_id, pid, end_time="2026-09-01 11:00")

    [entry] = db.fetch_query("select end_time, wage, cost from time").to_dict("records")
    assert entry["end_time"] == "2026-09-01 11:00:00"
    assert entry["wage"] == 1000  # keeps the wage it started at
    assert entry["cost"] == pytest.approx(2000, abs=0.005)


def test_timer_follows_every_raise_while_it_runs(acme):
    db = acme
    first_id, pid = _ids(db, "Acme", "Build")
    db.insert_timer_start_row(first_id, pid, "2026-09-01 09:00")

    db.insert_customer("Acme", "2026-09-10", 1200)
    db.insert_customer("Acme", "2026-09-20", 1400)

    latest_id, _ = _ids(db, "Acme", "Build")
    assert _running(db) == [latest_id]


def test_completed_entries_stay_on_their_version(acme):
    """History is untouched: only running entries move."""
    db = acme
    old_id, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(old_id, pid, "2026-08-03 09:00", "2026-08-03 11:00")

    db.insert_customer("Acme", "2026-09-01", 1200)

    [entry] = db.fetch_query("select customer_id, wage from time").to_dict("records")
    assert (entry["customer_id"], entry["wage"]) == (old_id, 1000)


# ── startup repair ──────────────────────────────────────────────────────────


def _orphan_the_running_timer(db, old_id):
    """Recreate the pre-5.1.1 state: the running entry left on the old id."""
    db.execute_query(
        "update time set customer_id = ? where end_time is null", (old_id,)
    )


def test_startup_reattaches_timers_orphaned_before_the_fix(acme):
    db = acme
    old_id, pid = _ids(db, "Acme", "Build")
    db.insert_timer_start_row(old_id, pid, "2026-09-01 09:00")
    db.insert_customer("Acme", "2026-09-01", 1200)
    new_id, _ = _ids(db, "Acme", "Build")
    _orphan_the_running_timer(db, old_id)

    db.initialize_db()  # runs at every startup

    assert _running(db) == [new_id]
    db.initialize_db()  # idempotent
    assert _running(db) == [new_id]


def test_startup_repair_lets_the_tracker_stop_a_duplicate_timer_too(acme):
    """Anyone already hit may have ticked the box and started a second timer.
    After the repair both sit on the current id; each tracker click stops the
    newest running one, so two clicks clear both."""
    db = acme
    old_id, pid = _ids(db, "Acme", "Build")
    db.insert_timer_start_row(old_id, pid, "2026-09-01 09:00")
    db.insert_customer("Acme", "2026-09-01", 1200)
    new_id, _ = _ids(db, "Acme", "Build")
    _orphan_the_running_timer(db, old_id)
    db.insert_timer_start_row(new_id, pid, "2026-09-01 10:00")  # the duplicate

    db.initialize_db()
    assert _running(db) == [new_id, new_id]

    db.insert_time_row(new_id, pid, end_time="2026-09-01 11:00")
    db.insert_time_row(new_id, pid, end_time="2026-09-01 11:00")
    assert _running(db) == []


def test_startup_repair_leaves_other_running_timers_alone(db):
    """A customer with no raise, and a disabled customer's timer on its latest
    version, are not orphans."""
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    db.insert_customer("Beta", "2026-01-01", 800)
    db.insert_project("Beta", "Ops")
    acme_id, build = _ids(db, "Acme", "Build")
    beta_id, ops = _ids(db, "Beta", "Ops")
    db.insert_timer_start_row(acme_id, build, "2026-09-01 09:00")
    db.insert_timer_start_row(beta_id, ops, "2026-09-01 09:00")
    db.disable_customer("Beta")

    db.initialize_db()

    assert _running(db) == [acme_id, beta_id]
