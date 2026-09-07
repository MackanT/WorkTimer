"""Tests for the timer dialogs' recommended-first work-item ordering."""

import pandas as pd

from src.pages.time_tracking import recommended_first


def _cust_df():
    # Epic 1 ── Feature 2 ── Story 4
    #        └─ Feature 3 ── Story 5
    # Epic 9 (unrelated), Story 6 (child of 3, Closed → not selectable)
    rows = [
        {"id": 1, "parent_id": None, "display_name": "Epic: 1 - Big"},
        {"id": 2, "parent_id": 1, "display_name": "Feature: 2 - A"},
        {"id": 3, "parent_id": 1, "display_name": "Feature: 3 - B"},
        {"id": 4, "parent_id": 2, "display_name": "User Story: 4 - A1"},
        {"id": 5, "parent_id": 3, "display_name": "User Story: 5 - B1"},
        {"id": 6, "parent_id": 3, "display_name": "User Story: 6 - closed"},
        {"id": 9, "parent_id": None, "display_name": "Epic: 9 - Other"},
    ]
    return pd.DataFrame(rows)


# What the dropdown offers (Active/New only — story 6 is closed, epic 1 closed too)
SELECTABLE = [
    "Feature: 2 - A",
    "Feature: 3 - B",
    "User Story: 4 - A1",
    "User Story: 5 - B1",
    "Epic: 9 - Other",
]


def test_epic_default_floats_whole_subtree_bfs():
    out, n = recommended_first(_cust_df(), SELECTABLE, 1)
    # BFS from epic 1: (1 not selectable) → features 2,3 → stories 4,5; rest after.
    assert out == [
        "Feature: 2 - A",
        "Feature: 3 - B",
        "User Story: 4 - A1",
        "User Story: 5 - B1",
        "Epic: 9 - Other",
    ]
    assert n == 4  # the first four are the recommended subtree


def test_feature_default_floats_its_stories_only():
    out, n = recommended_first(_cust_df(), SELECTABLE, 3)
    assert out[:2] == ["Feature: 3 - B", "User Story: 5 - B1"]
    assert n == 2
    # Remaining options keep their original relative order.
    assert out[2:] == ["Feature: 2 - A", "User Story: 4 - A1", "Epic: 9 - Other"]


def test_leaf_default_floats_itself():
    out, n = recommended_first(_cust_df(), SELECTABLE, 4)
    assert out[0] == "User Story: 4 - A1"
    assert n == 1
    assert len(out) == len(SELECTABLE)


def test_unknown_or_missing_default_keeps_order():
    out, n = recommended_first(_cust_df(), SELECTABLE, 12345)
    assert out[0] == SELECTABLE[0] and n == 0
    assert recommended_first(_cust_df(), SELECTABLE, None) == (SELECTABLE, 0)
    assert recommended_first(_cust_df(), SELECTABLE, "not-an-id") == (SELECTABLE, 0)
