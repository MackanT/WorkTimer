"""Characterisation tests: the Tasks page's reads, pinned as they behave in
5.1.x now that they live in the data layer (``Database.get_tasks`` and the
``TASK_SORTS`` map).

Part of the Postgres-port oracle (docs/v6_implementation.md, Phase 0.2).
Everything goes through public ``Database`` methods — no SQL in this file.

NULL ORDERING. SQLite sorts NULLs *first* in ascending order; Postgres sorts
them *last*. The due-date sorts guard against this with an explicit CASE, but
"Status", "Customer" and "Project" do not — the tests marked NULL ORDERING
pin SQLite's placement so the port either adds ``NULLS FIRST`` or changes them
as a reviewed diff.
"""

import pytest

pytestmark = pytest.mark.backends("sqlite", "postgres")

# title, priority, due date, customer, project, completed — no two tasks tie in
# any order asserted below.
TASKS = [
    ("Alpha task", "High", "2026-10-05", "Acme", "Build", False),
    ("Bravo task", "Low", "2026-10-01", "Beta", "Ops", False),
    ("Charlie task", "Critical", None, "Acme", "Support", False),
    ("Foxtrot task", "Medium", "2026-10-03", "Acme", "Build", False),
    ("Delta task", "Medium", "2026-09-20", "Beta", "Build", True),
    ("Echo task", "Someday", None, None, None, True),
]


@pytest.fixture
def tasks(db):
    # The customers and projects the tasks name. SQLite stores tasks' names as
    # free text; the v6 schema references real customers and projects.
    for customer, projects in {"Acme": ["Build", "Support"], "Beta": ["Ops", "Build"]}.items():
        db.insert_customer(customer, "2026-01-01", 1000)
        for project in projects:
            db.insert_project(customer, project)
    ids = {}
    for title, priority, due, customer, project, completed in TASKS:
        ok, msg, task = db.insert_task(
            title, priority=priority, due_date=due,
            customer_name=customer, project_name=project,
        )
        assert ok, msg
        ids[title] = int(task["task_id"])
        if completed:
            db.set_task_completion(ids[title], True)
    return db, ids


def _titles(db, sort_by, show_completed=False):
    return [t.removesuffix(" task") for t in db.get_tasks(sort_by, show_completed)["title"]]


def test_completed_tasks_only_when_asked_for(tasks):
    db, _ = tasks

    assert set(_titles(db, "Project")) == {"Alpha", "Bravo", "Charlie", "Foxtrot"}
    assert len(_titles(db, "Project", show_completed=True)) == 6


def test_due_date_sorts_put_undated_tasks_last_both_ways(tasks):
    db, _ = tasks

    assert _titles(db, "Due Date (Earliest First)") == ["Bravo", "Foxtrot", "Alpha", "Charlie"]
    assert _titles(db, "Due Date (Latest First)") == ["Alpha", "Foxtrot", "Bravo", "Charlie"]


def test_priority_sorts(tasks):
    db, _ = tasks

    assert _titles(db, "Priority (High to Low)") == ["Charlie", "Alpha", "Foxtrot", "Bravo"]
    assert _titles(db, "Priority (Low to High)") == ["Bravo", "Foxtrot", "Alpha", "Charlie"]
    # An unrecognised priority sorts after Low.
    assert _titles(db, "Priority (High to Low)", show_completed=True)[-1] == "Echo"


def test_status_sort_puts_undated_tasks_first_in_each_group(tasks):
    """NULL ORDERING — open before completed, then by due date with undated
    tasks first (SQLite). Postgres would put Charlie and Echo last in their
    groups."""
    db, _ = tasks

    assert _titles(db, "Status", show_completed=True) == [
        "Charlie", "Bravo", "Foxtrot", "Alpha", "Echo", "Delta"]


def test_customer_sort_puts_tasks_without_a_customer_first(tasks):
    """NULL ORDERING — Echo has no customer and Charlie no due date; both sort
    first in SQLite. Postgres would put them last."""
    db, _ = tasks

    assert _titles(db, "Customer", show_completed=True) == [
        "Echo", "Charlie", "Foxtrot", "Alpha", "Delta", "Bravo"]


def test_project_sort(tasks):
    db, _ = tasks

    assert _titles(db, "Project") == ["Foxtrot", "Alpha", "Bravo", "Charlie"]


def test_task_titles_are_listed_by_title(tasks):
    db, ids = tasks

    df = db.get_task_titles()

    assert df["title"].tolist() == [f"{t} task" for t in
                                    ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]]
    assert df["task_id"].tolist() == [ids[t] for t in df["title"]]


def test_task_by_id(tasks):
    db, ids = tasks

    task = db.get_task_by_id(ids["Foxtrot task"])

    assert (task.get("title"), task.get("priority"), task.get("due_date")) == (
        "Foxtrot task", "Medium", "2026-10-03")
    assert db.get_task_by_id(999) is None
