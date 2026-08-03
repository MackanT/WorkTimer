"""Tests for pure logic in src/pages/tasks.py."""

import inspect

from src.pages.tasks import (
    SORT_QUERIES,
    Task,
    create_task_card,
    extract_task_id,
    get_sort_query,
)


def test_extract_task_id():
    assert extract_task_id("My Task (ID: 42)") == 42
    assert extract_task_id("no id") is None


def test_sort_queries_single_source():
    # The toolbar select derives its options from these keys (§8.6).
    assert len(SORT_QUERIES) == 9
    assert get_sort_query("unknown fallback").startswith("ORDER BY")


def test_due_date_sorts_nulls_last_both_directions():
    """Fixed §1.7 — NULL due dates go to the bottom regardless of direction."""
    earliest = get_sort_query("Due Date (Earliest First)")
    latest = get_sort_query("Due Date (Latest First)")
    assert "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END ASC" in earliest
    assert "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END ASC" in latest
    assert earliest.rstrip().endswith("due_date ASC")
    assert latest.rstrip().endswith("due_date DESC")


def test_task_from_df_row_coerces_types():
    row = {
        "task_id": "5",
        "title": "T",
        "estimated_hours": "2.5",
        "actual_hours": "",
        "completed": 1,
        "due_date": "",
    }
    t = Task.from_df_row(row)
    assert t.task_id == 5
    assert t.estimated_hours == 2.5
    assert t.actual_hours == 0.0  # "" -> default
    assert t.completed is True
    assert t.due_date is None  # falsy -> None


def test_create_task_card_takes_task_object():
    """Card moved into tasks.py and takes the Task dataclass directly (§8.1)."""
    first_param = list(inspect.signature(create_task_card).parameters)[0]
    assert first_param == "task"
    assert not hasattr(Task, "to_columns_format")  # old label round-trip removed
