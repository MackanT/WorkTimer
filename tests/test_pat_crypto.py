"""PAT-at-rest encryption tests (tmp key files, no app boot)."""

import logging

from src.pat_crypto import decrypt_pat, encrypt_pat, is_encrypted

_log = logging.getLogger("test_pat")


def test_round_trip_creates_key_and_prefix(tmp_path):
    db = str(tmp_path / "wt.db")
    enc = encrypt_pat("secret-token", db, _log)
    assert is_encrypted(enc) and "secret-token" not in enc
    assert (tmp_path / ".pat_key").exists()
    assert decrypt_pat(enc, db, _log) == "secret-token"


def test_encrypt_is_idempotent_and_passthrough(tmp_path):
    db = str(tmp_path / "wt.db")
    enc = encrypt_pat("tok", db, _log)
    assert encrypt_pat(enc, db, _log) == enc          # no double encryption
    assert encrypt_pat("", db, _log) == ""            # clearing passes through
    assert decrypt_pat("plaintext", db, _log) == "plaintext"


def test_wrong_key_yields_empty(tmp_path):
    # A backup restored on another machine: encrypted value, different key.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    enc = encrypt_pat("tok", str(tmp_path / "a" / "wt.db"), _log)
    assert decrypt_pat(enc, str(tmp_path / "b" / "wt.db"), _log) == ""


def test_memory_db_skips_encryption():
    assert encrypt_pat("tok", ":memory:", _log) == "tok"


def test_database_writes_and_migration_encrypt(tmp_path):
    from src.database import Database

    db_path = str(tmp_path / "wt.db")
    db = Database(db_path, _log)
    db.initialize_db()

    # insert_customer encrypts on write
    db.insert_customer(
        "C1", "2026-01-01", 100, org_url="org", pat_token="plain-pat"
    )
    val = db.fetch_query(
        "select pat_token from customers where is_current = 1"
    ).iloc[0, 0]
    assert val.startswith("enc:")
    assert decrypt_pat(val, db_path, _log) == "plain-pat"

    # the startup migration catches rows that predate encryption
    db.execute_query("update customers set pat_token = 'legacy-pat'")
    db._encrypt_plaintext_pats()
    val = db.fetch_query(
        "select pat_token from customers where is_current = 1"
    ).iloc[0, 0]
    assert val.startswith("enc:")
    assert decrypt_pat(val, db_path, _log) == "legacy-pat"

    # update_customer re-encrypts a replaced PAT, and saving the enc: value
    # back (the form pre-fills it) does not double-encrypt
    db.update_customer("C1", "C1", pat_token=val)
    same = db.fetch_query(
        "select pat_token from customers where is_current = 1"
    ).iloc[0, 0]
    assert same == val
