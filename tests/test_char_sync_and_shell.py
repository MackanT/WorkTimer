"""Characterisation tests: the remaining single reads — the app shell's token
expiry warning (root.py), the tracker sync's watermarks (globals.py), the
work-item form's customer colour (work_item_forms.py) and Settings' tracker
types (settings.py) — pinned as they behave in 5.1.x now that they live in
the data layer.

Part of the Postgres-port oracle (docs/v6_implementation.md, Phase 0.2).
Everything goes through public ``Database`` methods — no SQL in this file.
"""

import pandas as pd


def test_tracker_expiries_list_only_trackers_with_a_date(db):
    db.insert_tracker("Ops DevOps", "devops", org_url="https://dev.azure.com/ops",
                      pat_token="p", token_expires="2026-10-15")
    db.insert_tracker("No Expiry", "devops", org_url="https://dev.azure.com/x", pat_token="p")
    db.insert_tracker("Blank Expiry", "devops", org_url="https://dev.azure.com/y",
                      pat_token="p", token_expires="")
    db.insert_tracker("Alpha Jira", "jira", jira_site="https://a.atlassian.net",
                      jira_email="a@b.c", jira_api_token="t", token_expires="2026-09-30")

    df = db.get_tracker_expiries()

    assert set(zip(df["tracker_name"], df["token_expires"])) == {
        ("Ops DevOps", "2026-10-15"), ("Alpha Jira", "2026-09-30")}


def test_tracker_types_by_name(db):
    db.insert_tracker("Zeta DevOps", "devops", org_url="https://dev.azure.com/z", pat_token="p")
    db.insert_tracker("Alpha Jira", "jira", jira_site="https://a.atlassian.net",
                      jira_email="a@b.c", jira_api_token="t")

    df = db.get_tracker_types()

    assert list(zip(df["tracker_name"], df["itype"])) == [
        ("Alpha Jira", "jira"), ("Zeta DevOps", "devops")]


def test_devops_watermarks_are_the_highest_id_and_change_per_customer(db):
    db.update_devops_data(pd.DataFrame([
        {"customer_name": "Acme", "id": 101, "title": "a", "changed_date": "2026-09-01T10:00:00"},
        {"customer_name": "Acme", "id": 250, "title": "b", "changed_date": "2026-08-01T10:00:00"},
        {"customer_name": "Beta", "id": 7, "title": "c", "changed_date": None},
    ]), mode="append")

    marks = {r["customer_name"]: r for r in db.get_devops_watermarks().to_dict("records")}

    # The highest id and the latest change need not be on the same item.
    assert (marks["Acme"]["max_id"], marks["Acme"]["max_changed_date"]) == (
        250, "2026-09-01T10:00:00")
    assert marks["Beta"]["max_id"] == 7
    assert marks["Beta"]["max_changed_date"] is None


def test_customer_color(db):
    db.insert_customer("Acme", "2026-01-01", 1000, color="#ff0000")
    db.insert_customer("Beta", "2026-01-01", 800)  # no colour
    db.insert_customer("Gamma", "2026-01-01", 700, color="#00ff00")
    db.disable_customer("Gamma")

    assert db.get_customer_color("Acme") == "#ff0000"
    assert db.get_customer_color("Beta") is None
    assert db.get_customer_color("Gamma") is None  # disabled: no current row
    assert db.get_customer_color("Nobody") is None
