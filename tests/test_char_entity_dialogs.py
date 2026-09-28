"""Characterisation tests: the entity dialogs' data sources (add_data.py —
customers, projects, trackers, bonus), pinned as they behave in 5.1.x now that
they live in the data layer.

Part of the Postgres-port oracle (docs/v6_implementation.md, Phase 0.2).
Everything goes through public ``Database`` methods — no SQL in this file.

Two pinned quirks are reviewed diffs on Postgres (Phase 2):
``test_customer_dropdown_order`` and ``test_disabled_project_with_a_name_in_use``.
"""

import pandas as pd
import pytest

pytestmark = pytest.mark.backends("sqlite", "postgres")


def _values(df, *cols):
    return [tuple(r) for r in df[list(cols)].itertuples(index=False)]


# ── customers ───────────────────────────────────────────────────────────────


def test_customer_dropdown_order(db):
    """REVIEWED DIFF (Phase 2) — decided: the Time Tracker's order.

    SQLite's query has no ORDER BY, so dropdowns show its row order: creation
    order, except that a wage change creates a new row and moves that
    customer to the end. Postgres guarantees no order, so the port uses the
    user's sort order, then the name — unchanged by a raise."""
    for name in ["Charlie", "Alpha", "Bravo", "Delta"]:
        db.insert_customer(name, "2026-01-01", 1000)
    db.disable_customer("Delta")
    before = ["Charlie", "Alpha", "Bravo"] if db.backend == "sqlite" else ["Alpha", "Bravo", "Charlie"]
    assert db.get_current_customer_names()["customer_name"].tolist() == before

    db.insert_customer("Charlie", "2026-09-01", 1200)  # raise (SQLite: a new row)

    assert db.get_current_customer_names()["customer_name"].tolist() == [
        "Alpha", "Bravo", "Charlie"]


def test_current_customer_details_for_the_update_dialog(db):
    db.insert_tracker("Ops DevOps", "devops", org_url="https://dev.azure.com/ops", pat_token="pat")
    db.insert_customer("Acme", "2026-01-01", 1000, tracker_name="Ops DevOps",
                       tracker_project="Platform", expected_work_pct=40, color="#123456")
    db.insert_customer("Beta", "2026-01-01", 800)  # no tracker

    rows = {r["customer_name"]: r for r in db.get_current_customer_details().to_dict("records")}

    assert rows["Acme"]["tracker_name"] == "Ops DevOps"
    assert rows["Acme"]["tracker_project"] == "Platform"
    assert rows["Acme"]["expected_work_pct"] == 40
    assert rows["Acme"]["color"] == "#123456"
    assert rows["Beta"]["tracker_name"] is None


def test_disabled_customers_offered_for_re_enable(db):
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_customer("Acme", "2026-09-01", 1200)  # old version disabled by the raise
    db.insert_customer("Beta", "2026-01-01", 800)
    db.disable_customer("Beta")

    names = db.get_disabled_customer_names()["customer_name"].tolist()

    # Acme's superseded version is not a candidate — Acme is still current.
    assert names == ["Beta"]


# ── projects ────────────────────────────────────────────────────────────────


def test_enabled_projects_with_their_customer_and_work_item(db):
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build", git_id=101)
    db.insert_project("Acme", "Old")
    db.disable_project("Acme", "Old")

    df = db.get_current_projects_with_customer()

    assert _values(df, "project_name", "customer_name") == [("Build", "Acme")]
    assert df["git_id"].tolist() == [101]
    assert db.get_current_project_names()["project_name"].tolist() == ["Build"]


def test_disabled_projects_offered_for_re_enable(db):
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    db.insert_project("Acme", "Old")
    db.disable_project("Acme", "Old")

    df = db.get_disabled_projects_with_customer()

    assert _values(df, "project_name", "customer_name") == [("Old", "Acme")]


def test_disabled_project_with_a_name_in_use(db):
    """REVIEWED DIFF (Phase 2) — a SQLite bug, fixed on Postgres.

    SQLite's re-enable candidates exclude any project whose *name* is enabled
    anywhere, so Beta's disabled "Build" cannot be re-enabled from the dialog
    while Acme has an enabled "Build". Postgres goes by the project itself.
    """
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_customer("Beta", "2026-01-01", 800)
    db.insert_project("Acme", "Build")
    db.insert_project("Beta", "Build")
    db.disable_project("Beta", "Build")

    candidates = _values(db.get_disabled_projects_with_customer(), "project_name", "customer_name")
    assert candidates == ([] if db.backend == "sqlite" else [("Build", "Beta")])


# ── trackers ────────────────────────────────────────────────────────────────


def test_trackers_by_name_with_credentials_as_stored(db):
    db.insert_tracker("Zeta DevOps", "devops", org_url="https://dev.azure.com/zeta",
                      pat_token="pat-zeta", token_expires="2027-01-31")
    db.insert_tracker("Alpha Jira", "jira", jira_site="https://alpha.atlassian.net",
                      jira_email="me@example.com", jira_api_token="tok")

    assert db.get_tracker_names()["tracker_name"].tolist() == ["Alpha Jira", "Zeta DevOps"]

    rows = db.get_trackers().to_dict("records")
    assert [r["tracker_name"] for r in rows] == ["Alpha Jira", "Zeta DevOps"]
    jira, devops = rows
    assert (jira["integration_type"], jira["org_url"]) == ("jira", "https://alpha.atlassian.net")
    assert (devops["integration_type"], devops["org_url"]) == ("devops", "https://dev.azure.com/zeta")
    assert devops["token_expires"] == "2027-01-31"
    # Credentials come back encrypted, never in plaintext.
    assert all(r["pat_token"].startswith("enc:") for r in rows)
    assert pd.isna(jira["token_expires"])
