"""Characterisation tests: the command palette's reads, pinned as they behave
in 5.1.x now that they live in the data layer.

Part of the Postgres-port oracle (docs/v6_implementation.md, Phase 0.2).
Everything goes through public ``Database`` methods — no SQL in this file.
(The palette's other two reads, ``get_running_timer_names`` and
``get_current_customers``, are pinned in the Time Tracker and Reports files.)
"""

import pytest

pytestmark = pytest.mark.backends("sqlite", "postgres")


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


def _rows(df, *cols):
    return [tuple(r) for r in df[list(cols)].itertuples(index=False)]


def test_running_timers_with_names_are_ordered_by_name(db):
    """The palette's "Stop timer" commands. A disabled customer's running
    timer is still offered, although the Time Tracker hides that customer."""
    for name in ["Charlie", "Alpha", "Bravo"]:
        db.insert_customer(name, "2026-01-01", 1000)
    db.insert_project("Charlie", "Ops")
    db.insert_project("Alpha", "Zeta")
    db.insert_project("Bravo", "Misc")
    charlie, ops = _ids(db, "Charlie", "Ops")
    alpha, zeta = _ids(db, "Alpha", "Zeta")
    bravo, misc = _ids(db, "Bravo", "Misc")
    for cid, pid in [(charlie, ops), (alpha, zeta), (bravo, misc)]:
        db.insert_timer_start_row(cid, pid, "2026-09-01 09:00")
    db.disable_customer("Bravo")

    df = db.get_running_timers_with_names()

    assert _rows(df, "customer_name", "project_name") == [
        ("Alpha", "Zeta"), ("Bravo", "Misc"), ("Charlie", "Ops")]
    assert _rows(df, "customer_id", "project_id") == [
        (alpha, zeta), (bravo, misc), (charlie, ops)]


def test_current_customer_projects_are_enabled_pairs_by_name(db):
    """The palette's "Start timer" commands."""
    for name in ["Charlie", "Alpha", "Bravo"]:
        db.insert_customer(name, "2026-01-01", 1000)
    for customer, project in [("Charlie", "Build"), ("Alpha", "Zeta"),
                              ("Alpha", "Apex"), ("Alpha", "Old"), ("Bravo", "Misc")]:
        db.insert_project(customer, project)
    db.disable_project("Alpha", "Old")
    db.disable_customer("Bravo")

    df = db.get_current_customer_projects()

    assert _rows(df, "customer_name", "project_name") == [
        ("Alpha", "Apex"), ("Alpha", "Zeta"), ("Charlie", "Build")]
    assert _rows(df, "customer_id", "project_id")[0] == _ids(db, "Alpha", "Apex")
