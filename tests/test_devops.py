"""Tests for src/devops.py — hierarchy dataframe + consistent return arity."""

import logging

import pandas as pd

from src.devops import DevOpsManager

_LOG = logging.getLogger("worktimer.tests")
_LOG.addHandler(logging.NullHandler())


class _FakeItem:
    def __init__(self, item_id, fields):
        self.id = item_id
        self.fields = fields


class _FakeClient:
    def __init__(self, items):
        self._items = items

    def get_workitem_level(self, **kwargs):
        return True, self._items


def _empty_manager():
    return DevOpsManager(
        pd.DataFrame(columns=["customer_name", "pat_token", "org_url"]), _LOG
    )


def test_manager_skips_customers_without_credentials():
    df = pd.DataFrame([{"customer_name": "A", "pat_token": "", "org_url": ""}])
    mgr = DevOpsManager(df, _LOG)
    assert mgr.clients == {}


def test_get_description_always_returns_four_tuple():
    """§9 — the caller unpacks 4 values unconditionally; no-client path must match."""
    result = _empty_manager().get_description("Nobody", 1)
    assert len(result) == 4
    assert result[0] is False
    assert isinstance(result[3], dict)


def test_get_epics_feature_df_builds_hierarchy():
    """§8.3 — one loop replaced the tripled per-type blocks; parents must be right."""
    items = [
        _FakeItem(1, {
            "System.WorkItemType": "Epic", "System.Title": "E",
            "System.State": "Active", "System.BoardColumn": "Doing",
            "Microsoft.VSTS.Common.Priority": 2,
        }),
        _FakeItem(2, {
            "System.WorkItemType": "Feature", "System.Title": "F",
            "System.State": "Active", "System.Parent": 1,
            "System.BoardColumn": "Doing", "Microsoft.VSTS.Common.Priority": 2,
        }),
        _FakeItem(3, {
            "System.WorkItemType": "User Story", "System.Title": "US",
            "System.State": "Active", "System.Parent": 2,
            "System.BoardColumn": "New", "Microsoft.VSTS.Common.Priority": 3,
        }),
        _FakeItem(4, {"System.WorkItemType": "Task", "System.Title": "ignored"}),
    ]
    mgr = _empty_manager()
    mgr.clients = {"CustA": _FakeClient(items)}

    ok, df = mgr.get_epics_feature_df()
    assert ok
    # The non-Epic/Feature/Story item is dropped.
    assert set(df["id"]) == {1, 2, 3}

    epic = df[df["id"] == 1].iloc[0]
    assert epic["type"] == "Epic" and pd.isna(epic["parent_id"])

    feature = df[df["id"] == 2].iloc[0]
    assert feature["type"] == "Feature" and feature["parent_id"] == 1

    story = df[df["id"] == 3].iloc[0]
    assert story["type"] == "User Story" and story["parent_id"] == 2
