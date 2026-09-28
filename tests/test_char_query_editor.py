"""Characterisation tests: the query editor's data-layer calls, pinned as they
behave in 5.1.x — saved-query management, running the user's SQL, and the
syntax check.

Part of the Postgres-port oracle (docs/v6_implementation.md). One pinned
behaviour changes deliberately in Phase 3 — see
``test_user_sql_can_write_today``.

Everything runs on both backends. Phase 3's lockdown (Postgres) is marked
REVIEWED DIFF where it changes an expectation.
"""

import pytest

BOTH = pytest.mark.backends("sqlite", "postgres")


def _saved(db) -> dict:
    df = db.get_query_list()
    return dict(zip(df["query_name"], df["query_sql"]))


@BOTH
def test_saved_query_lifecycle(db):
    db.insert_saved_query("mine", "select 1 as x")
    assert _saved(db)["mine"] == "select 1 as x"

    db.update_saved_query("mine", "select 2 as y")
    assert _saved(db)["mine"] == "select 2 as y"

    db.delete_saved_query("mine")
    assert "mine" not in _saved(db)


@BOTH
def test_saved_query_names_are_unique(db):
    db.insert_saved_query("mine", "select 1")

    with pytest.raises(Exception):
        db.insert_saved_query("mine", "select 2")
    assert _saved(db)["mine"] == "select 1"


@BOTH
def test_user_sql_returns_rows(db):
    df = db.run_user_query("select 1 as one, 'a' as letter")

    assert df.to_dict("records") == [{"one": 1, "letter": "a"}]


@BOTH
def test_user_sql_writes(db):
    """REVIEWED DIFF (Phase 3): on Postgres user SQL runs on a read-only role
    and anything but a single SELECT is refused. SQLite (5.x) lets a write
    through: it commits and returns None."""
    db.insert_saved_query("mine", "select 1")
    write = "update queries set query_sql = 'x' where query_name = 'mine'"

    if db.backend == "postgres":
        with pytest.raises(ValueError, match="Only SELECT"):
            db.run_user_query(write)
        assert _saved(db)["mine"] == "select 1"
    else:
        assert db.run_user_query(write) is None
        assert _saved(db)["mine"] == "x"


@BOTH
def test_syntax_check_compiles_without_running(db):
    """REVIEWED DIFF (Phase 3): on Postgres a write fails the check itself."""
    db.insert_saved_query("mine", "select 1")

    if db.backend == "postgres":
        with pytest.raises(ValueError, match="Only SELECT"):
            db.check_user_query("delete from saved_queries")
    else:
        db.check_user_query("delete from queries")  # valid — and not executed

    assert "mine" in _saved(db)
    with pytest.raises(Exception):
        db.check_user_query("selec broken")
