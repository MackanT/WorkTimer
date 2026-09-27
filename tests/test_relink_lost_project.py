"""Regression (5.1.2): entries that lost their project but kept its name.

Some older entries have project_id 0 while still carrying project_name. They
count on Reports (grouped by name) but vanish from the Time Tracker and
"Manage entries" (joined on id). The startup repair re-links them — only when
exactly one project of that name exists under the entry's own customer.
"""

import pytest


def _ids(db, customer: str, project: str) -> tuple[int, int]:
    df = db.get_data_input_list()
    row = df[
        (df.customer_name == customer)
        & (df.c_current == 1)
        & (df.project_name == project)
    ]
    assert len(row) == 1
    return int(row.iloc[0].customer_id), int(row.iloc[0].project_id)


def _entry(db, time_id: int) -> dict:
    return db.fetch_query(
        "select project_id, project_name, total_time, wage, cost from time where time_id = ?",
        (time_id,),
    ).to_dict("records")[0]


def _lose_project_keep_name(db, time_id: int, name: str = None) -> None:
    """Recreate the damaged state found in real data: project_id 0 with the
    project name still on the entry. (Setting project_id alone fires a trigger
    that clears the name, so the name is written back separately.)"""
    name = name or _entry(db, time_id)["project_name"]
    db.execute_query("update time set project_id = 0 where time_id = ?", (time_id,))
    db.execute_query("update time set project_name = ? where time_id = ?", (name, time_id))


@pytest.fixture
def acme(db):
    """Acme (Build, Support); one 2 h entry on Build logged at 1000/h; then a
    raise, so the entry sits on a superseded customer version — as all the
    real damaged entries do."""
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    db.insert_project("Acme", "Support")
    cid, build = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, build, "2026-08-03 09:00", "2026-08-03 11:00")
    db.insert_customer("Acme", "2026-09-01", 1200)
    time_id = int(db.fetch_query("select time_id from time").iloc[0, 0])
    return db, time_id, build


def test_startup_relinks_an_entry_that_lost_its_project(acme):
    db, time_id, build = acme
    before = _entry(db, time_id)
    _lose_project_keep_name(db, time_id)
    assert db.get_customer_ui_list("20260801", "20260831")["total_time"].sum() == 0  # invisible

    db.initialize_db()  # runs at every startup

    after = _entry(db, time_id)
    assert after["project_id"] == build
    assert after == before  # name, duration, wage and cost all as they were
    assert db.get_customer_ui_list("20260801", "20260831")["total_time"].sum() == pytest.approx(2.0)


def test_relink_is_idempotent_and_leaves_healthy_entries_alone(acme):
    db, time_id, build = acme
    cid, support = _ids(db, "Acme", "Support")
    db.insert_manual_time_row(cid, support, "2026-09-02 09:00", "2026-09-02 10:00")
    healthy = db.fetch_query("select * from time where time_id != ?", (time_id,))
    _lose_project_keep_name(db, time_id)

    db.initialize_db()
    db.initialize_db()

    assert _entry(db, time_id)["project_id"] == build
    assert db.fetch_query("select * from time where time_id != ?", (time_id,)).equals(healthy)


def test_an_ambiguous_name_is_left_alone(acme):
    db, time_id, _ = acme
    cid, _ = _ids(db, "Acme", "Build")
    db.execute_query(  # a second "Build" under the same customer (legacy data)
        "insert into projects (customer_id, project_name, is_current) values (?, 'Build', 0)", (cid,))
    _lose_project_keep_name(db, time_id)

    db.initialize_db()

    assert _entry(db, time_id)["project_id"] == 0


def test_only_the_entrys_own_customer_is_searched(acme):
    db, time_id, _ = acme
    db.insert_customer("Beta", "2026-01-01", 800)
    db.insert_project("Beta", "Research")
    _lose_project_keep_name(db, time_id, name="Research")  # a name only Beta has

    db.initialize_db()

    assert _entry(db, time_id)["project_id"] == 0


def test_an_entry_whose_name_was_cleared_too_is_left_alone(acme):
    """The query-editor row-edit bug cleared the name as well — nothing to go
    on, so the repair can't help those."""
    db, time_id, _ = acme
    db.execute_query("update time set project_id = 0 where time_id = ?", (time_id,))
    assert _entry(db, time_id)["project_name"] is None

    db.initialize_db()

    assert _entry(db, time_id)["project_id"] == 0
