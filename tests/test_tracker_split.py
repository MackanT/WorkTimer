"""Tracker/customer split: trackers table CRUD, the legacy-credentials
migration, customer linking, and the connection-resolution join."""

import logging

import pytest

from src.database import Database
from src.pat_crypto import decrypt_pat

_log = logging.getLogger("test_tracker_split")


@pytest.fixture()
def db(tmp_path):
    d = Database(str(tmp_path / "wt.db"), _log)
    d.initialize_db()
    return d


def _make_legacy(db, specs):
    """Simulate a pre-split database: re-add the retired credential columns
    and stamp legacy credentials onto customers (unlinked)."""
    cols = db._get_table_columns("customers")
    if "pat_token" not in cols:
        db.execute_query("alter table customers add column pat_token text")
    if "org_url" not in cols:
        db.execute_query("alter table customers add column org_url text")
    for cname, org, pat, itype in specs:
        db.execute_query(
            "update customers set org_url = ?, pat_token = ?, "
            "integration_type = ?, tracker_id = null where customer_name = ?",
            (org, pat, itype, cname),
        )


def test_tracker_crud_encrypts_pat(db):
    db.insert_tracker("RF Azure", "devops", "rforg", "azure-pat")
    tid = db.get_tracker_id("RF Azure")
    assert tid

    stored = db.fetch_query("select pat_token from trackers").iloc[0, 0]
    assert stored.startswith("enc:")
    assert decrypt_pat(stored, db.db_file, _log) == "azure-pat"

    with pytest.raises(ValueError):
        db.insert_tracker("RF Azure")  # duplicate name refused

    db.update_tracker("RF Azure", new_tracker_name="RF ADO",
                      integration_type="devops", org_url="rforg2",
                      pat_token="new-pat")
    row = db.fetch_query(
        "select tracker_name, org_url, pat_token from trackers"
    ).iloc[0]
    assert row["tracker_name"] == "RF ADO" and row["org_url"] == "rforg2"
    assert decrypt_pat(row["pat_token"], db.db_file, _log) == "new-pat"

    # Saving the enc: value back (form pre-fill) must not double-encrypt.
    db.update_tracker("RF ADO", pat_token=row["pat_token"])
    same = db.fetch_query("select pat_token from trackers").iloc[0, 0]
    assert same == row["pat_token"]


def test_delete_tracker_detaches_customers(db):
    db.insert_tracker("T1", "devops", "org", "pat")
    db.insert_customer("C1", "2026-01-01", 100, tracker_name="T1")
    assert db.fetch_query(
        "select tracker_id from customers where is_current = 1"
    ).iloc[0, 0] == db.get_tracker_id("T1")

    db.delete_tracker("T1")
    assert db.fetch_query("select count(*) from trackers").iloc[0, 0] == 0
    linked = db.fetch_query(
        "select tracker_id from customers where is_current = 1"
    ).iloc[0, 0]
    assert linked is None or (linked != linked)  # NULL (pandas NaN)

    with pytest.raises(ValueError):
        db.delete_tracker("T1")  # already gone


def test_migration_creates_and_dedupes_trackers(db):
    # Legacy world: credentials embedded on the customer rows, no links.
    db.insert_customer("A", "2026-01-01", 100)
    db.insert_customer("B", "2026-01-01", 100)
    db.insert_customer("J", "2026-01-01", 100)
    _make_legacy(db, [
        ("A", "sharedorg", "sharedpat", "devops"),
        ("B", "sharedorg", "sharedpat", "devops"),
        ("J", "site.atlassian.net", "me@x.com:tok", "jira"),
    ])

    # The startup sequence: encrypt → link → drop.
    db._encrypt_plaintext_pats()
    db._migrate_customer_trackers()

    trackers = db.fetch_query(
        "select tracker_id, tracker_name, integration_type from trackers"
    )
    # A and B share credentials → one tracker; J gets its own. Dedupe works
    # on the DECRYPTED PATs (identical plaintext, distinct ciphertexts).
    assert len(trackers) == 2
    assert set(trackers["integration_type"]) == {"devops", "jira"}

    links = db.fetch_query(
        "select customer_name, tracker_id from customers where is_current = 1"
    ).set_index("customer_name")["tracker_id"]
    assert links["A"] == links["B"]
    assert links["J"] != links["A"]

    # Everyone linked → the legacy columns get dropped …
    db._drop_legacy_customer_credentials()
    assert "pat_token" not in db._get_table_columns("customers")
    assert "org_url" not in db._get_table_columns("customers")
    # … and the repaired default 'customers' query is stored normalized
    # (dedented — raw source indentation once leaked into the query page).
    q = db.fetch_query(
        "select query_sql from queries where query_name = 'customers'"
    ).iloc[0, 0]
    assert q == q.strip() and "\n     customer_id" in q

    # … and the second run of the whole sequence is a no-op.
    db._encrypt_plaintext_pats()
    db._migrate_customer_trackers()
    db._drop_legacy_customer_credentials()
    assert len(db.fetch_query("select * from trackers")) == 2


def test_customer_versioning_inherits_tracker_link(db):
    db.insert_tracker("T1", "devops", "org", "pat")
    db.insert_customer("C1", "2026-01-01", 100, tracker_name="T1")
    # Wage change = new customer version, tracker not re-picked.
    db.insert_customer("C1", "2026-06-01", 120)
    row = db.fetch_query(
        "select wage, tracker_id from customers where is_current = 1"
    ).iloc[0]
    assert row["wage"] == 120
    assert int(row["tracker_id"]) == db.get_tracker_id("T1")


def test_update_customer_links_and_unlinks(db):
    db.insert_tracker("T1", "devops", "org", "pat")
    db.insert_tracker("T2", "jira", "site", "e@x:tok")
    db.insert_customer("C1", "2026-01-01", 100, tracker_name="T1")

    db.update_customer("C1", "C1", tracker_name="T2")
    assert db.fetch_query(
        "select tracker_id from customers where is_current = 1"
    ).iloc[0, 0] == db.get_tracker_id("T2")

    db.update_customer("C1", "C1", tracker_name="")  # unlink
    linked = db.fetch_query(
        "select tracker_id from customers where is_current = 1"
    ).iloc[0, 0]
    assert linked is None or (linked != linked)  # NULL


def test_connection_join_prefers_tracker_credentials(db):
    db.insert_tracker("T1", "jira", "site.atlassian.net", "e@x.com:tok")
    db.insert_customer("C1", "2026-01-01", 100, tracker_name="T1")
    db.insert_customer("C2", "2026-01-01", 100)  # unlinked, legacy creds
    db.insert_customer("C3", "2026-01-01", 100)  # no connection at all
    # Pre-split leftovers: stale credentials on the linked C1, real legacy
    # credentials on the unlinked C2.
    _make_legacy(db, [("C2", "legacyorg", "legacypat", "devops")])
    db.execute_query(
        "update customers set org_url = 'old-org', pat_token = 'old-pat' "
        "where customer_name = 'C1'"
    )

    df = db.get_tracker_connections().set_index("customer_name")
    assert df.loc["C1", "org_url"] == "site.atlassian.net"  # tracker wins
    assert df.loc["C1", "integration_type"] == "jira"
    assert decrypt_pat(df.loc["C1", "pat_token"], db.db_file, _log) == "e@x.com:tok"
    assert df.loc["C2", "org_url"] == "legacyorg"           # fallback path
    assert df.loc["C2", "integration_type"] == "devops"
    assert "C3" not in df.index

    # The drop is BLOCKED while an unlinked customer still needs the fallback…
    db._drop_legacy_customer_credentials()
    assert "pat_token" in db._get_table_columns("customers")

    # …and proceeds once nothing does; the query flips to tracker-only.
    db.execute_query(
        "update customers set org_url = null, pat_token = null "
        "where customer_name = 'C2'"
    )
    db._drop_legacy_customer_credentials()
    assert "pat_token" not in db._get_table_columns("customers")
    df = db.get_tracker_connections()
    assert set(df["customer_name"]) == {"C1"}
