"""Regression (5.1.2): the query editor's row edit of a time entry logged
before its customer's raise.

A raise gives the customer a new id and moves its projects there, but an
entry keeps the id it was logged under. The dialog listed projects — and the
save resolved the chosen project — by that old id: the dropdown came up empty,
and an Update wrote project_id 0, dropping the entry from the Time Tracker.
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


@pytest.fixture
def pre_raise_entry(db):
    """A 2 h Acme/Build entry logged at 1000/h, then a raise to 1200/h."""
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    db.insert_project("Acme", "Support")
    cid, build = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, build, "2026-08-03 09:00", "2026-08-03 11:00")
    db.insert_customer("Acme", "2026-09-01", 1200)
    time_id = int(db.fetch_query("select time_id from time").iloc[0, 0])
    return db, time_id


def _entry(db) -> dict:
    return db.fetch_query(
        "select project_id, project_name, total_time, wage, cost from time"
    ).to_dict("records")[0]


def _save(db, time_id, project_name):
    """What the dialog's Update button sends: the project, a new end time."""
    db.update_data_from_query(
        table_name="time", pk_data=("time_id", time_id), project_name=project_name,
        start_time="2026-08-03 09:00:00", end_time="2026-08-03 12:00:00",
        comment="fixed end", git_id=0,
    )


def test_dialog_lists_the_customers_projects_for_a_pre_raise_entry(pre_raise_entry):
    db, time_id = pre_raise_entry
    row = db.get_query_edit_data("time", time_id).iloc[0]

    df = db.get_sibling_project_names(int(row["project_id"]))

    assert set(df["project_name"]) == {"Build", "Support"}


def test_saving_a_pre_raise_entry_keeps_its_project(pre_raise_entry):
    db, time_id = pre_raise_entry
    _, build = _ids(db, "Acme", "Build")

    _save(db, time_id, "Build")

    e = _entry(db)
    assert (e["project_id"], e["project_name"]) == (build, "Build")
    assert e["total_time"] == pytest.approx(3.0, abs=1e-6)
    assert (e["wage"], e["cost"]) == (1000, pytest.approx(3000, abs=0.005))  # its own wage


def test_saving_can_move_a_pre_raise_entry_to_another_project(pre_raise_entry):
    db, time_id = pre_raise_entry
    _, support = _ids(db, "Acme", "Support")

    _save(db, time_id, "Support")

    assert (_entry(db)["project_id"], _entry(db)["project_name"]) == (support, "Support")


def test_an_unknown_project_is_refused_instead_of_clearing_the_entry(pre_raise_entry):
    db, time_id = pre_raise_entry
    before = _entry(db)

    with pytest.raises(ValueError, match="No project named 'Nope'"):
        _save(db, time_id, "Nope")

    assert _entry(db) == before
