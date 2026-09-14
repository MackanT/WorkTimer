"""Tests for the pluggable tracker layer (src/trackers/)."""

import logging
import sqlite3
from types import SimpleNamespace

import pandas as pd

from src.trackers.azure import AzureDevOpsProvider
from src.trackers.base import DEFAULT_TYPE_HIERARCHY, WORK_ITEM_COLUMNS
from src.trackers.registry import create_provider_for_row, get_provider_class
from src.tracker_manager import TrackerManager

_log = logging.getLogger("test_trackers")


def _row(**over):
    base = {
        "customer_name": "Acme",
        "pat_token": "secret",
        "org_url": "acme-org",
        "tracker_project": None,
        "integration_type": "devops",
    }
    base.update(over)
    return base


# ── registry ────────────────────────────────────────────────────────────────

def test_devops_provider_is_registered():
    assert get_provider_class("devops") is AzureDevOpsProvider


def test_unknown_integration_type_returns_none():
    assert create_provider_for_row(_row(integration_type="jira"), _log) is None


def test_missing_integration_type_defaults_to_devops():
    p = create_provider_for_row(_row(integration_type=None), _log)
    assert isinstance(p, AzureDevOpsProvider)


def test_missing_credentials_returns_none():
    assert create_provider_for_row(_row(pat_token=""), _log) is None
    assert create_provider_for_row(_row(org_url="none"), _log) is None


# ── the azure provider ──────────────────────────────────────────────────────

def test_from_customer_row_builds_org_url_and_customer():
    p = create_provider_for_row(_row(), _log)
    assert p.organization_url == "https://dev.azure.com/acme-org"
    assert p.customer_name == "Acme"
    assert p.type_hierarchy() == ("Epic", "Feature", "User Story")
    assert p.type_hierarchy() == DEFAULT_TYPE_HIERARCHY


def test_owns_attachment_url_guards_foreign_hosts():
    p = create_provider_for_row(_row(), _log)
    ours = "https://dev.azure.com/acme-org/_apis/wit/attachments/abc"
    assert p.owns_attachment_url(ours)
    assert not p.owns_attachment_url(
        "https://dev.azure.com/other-org/_apis/wit/attachments/abc"
    )
    assert not p.owns_attachment_url("https://dev.azure.com/acme-org/other/path")


def test_fetch_work_items_normalizes_to_canonical_schema(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    items = [
        SimpleNamespace(id=1, fields={
            "System.WorkItemType": "Epic", "System.Title": "Big",
            "System.State": "Active", "System.BoardColumn": "Doing",
            "System.ChangedDate": "2026-01-01",
        }),
        SimpleNamespace(id=2, fields={
            "System.WorkItemType": "User Story", "System.Title": "Small",
            "System.State": "New", "System.Parent": 1,
            "System.BoardColumnDone": True,
            "System.AssignedTo": {"displayName": "Dev"},
            "Microsoft.VSTS.Common.Priority": 2,
            "System.Description": "<p>Fix the <b>login&nbsp;flow</b></p>",
        }),
        SimpleNamespace(id=3, fields={"System.WorkItemType": "Task"}),  # filtered
    ]
    monkeypatch.setattr(
        p, "get_workitem_level", lambda **kw: (True, items)
    )
    df = p.fetch_work_items()
    assert list(df.columns) == WORK_ITEM_COLUMNS
    assert len(df) == 2  # Task excluded
    epic = df[df["id"] == 1].iloc[0]
    story = df[df["id"] == 2].iloc[0]
    assert epic["customer_name"] == "Acme"
    assert pd.isna(epic["parent_id"])         # root level has no parent
    assert story["parent_id"] == 1
    assert story["board_column_done"] == 1
    assert story["assigned_to"] == "Dev"
    # Description cached as searchable plain text: tags stripped, entities decoded.
    assert story["description"] == "Fix the login flow"
    assert epic["description"] == ""


def test_fetch_work_items_empty_result(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    monkeypatch.setattr(p, "get_workitem_level", lambda **kw: (True, []))
    df = p.fetch_work_items()
    assert df.empty and list(df.columns) == WORK_ITEM_COLUMNS


# ── the provider-neutral manager ────────────────────────────────────────────

def test_manager_builds_clients_via_registry(monkeypatch):
    monkeypatch.setattr(AzureDevOpsProvider, "connect", lambda self: None)
    df = pd.DataFrame([_row(), _row(customer_name="Beta", org_url="beta-org")])
    mgr = TrackerManager(df, _log)
    assert set(mgr.clients) == {"Acme", "Beta"}
    assert all(isinstance(c, AzureDevOpsProvider) for c in mgr.clients.values())


def test_manager_skips_unknown_provider_and_failed_connect(monkeypatch):
    def _boom(self):
        raise Exception("bad credentials")

    monkeypatch.setattr(AzureDevOpsProvider, "connect", _boom)
    df = pd.DataFrame([_row(), _row(customer_name="J", integration_type="jira")])
    mgr = TrackerManager(df, _log)
    assert mgr.clients == {}  # jira unknown, Acme failed to connect


def test_manager_concats_provider_frames(monkeypatch):
    monkeypatch.setattr(AzureDevOpsProvider, "connect", lambda self: None)
    mgr = TrackerManager(pd.DataFrame([_row()]), _log)
    fake = pd.DataFrame([dict.fromkeys(WORK_ITEM_COLUMNS, None)])
    monkeypatch.setattr(
        mgr.clients["Acme"], "fetch_work_items", lambda **kw: fake
    )
    status, df = mgr.get_epics_feature_df()
    assert status and len(df) == 1


# ── compat + migration ──────────────────────────────────────────────────────

def test_legacy_imports_still_work():
    from src.tracker_manager import AzureDevOpsClient, TrackerManager as M, _choose_project  # noqa

    assert issubclass(AzureDevOpsProvider, AzureDevOpsClient)


def test_old_db_gains_integration_type_column(tmp_path, null_logger):
    """A pre-5.0.5 customers table must gain integration_type (default devops)."""
    from src.database import Database

    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.execute(
        "create table customers (customer_id integer primary key autoincrement, "
        "customer_name text, start_date datetime, wage real, pat_token text, "
        "org_url text, is_current integer)"
    )
    con.execute(
        "insert into customers (customer_name, is_current) values ('Old', 1)"
    )
    con.commit()
    con.close()

    Database(path, null_logger).initialize_db()

    con = sqlite3.connect(path)
    val = con.execute(
        "select integration_type from customers where customer_name = 'Old'"
    ).fetchone()[0]
    con.close()
    assert val == "devops"  # backfilled by the column default
