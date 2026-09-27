"""The Postgres test fixtures (v6 phase 1.1): the dev server is what the v6
schema needs, and every test gets a fresh, empty database of its own."""

import pytest

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.postgres


def test_server_has_what_the_v6_schema_needs(pg_db):
    with psycopg.connect(pg_db) as conn:
        assert conn.info.server_version >= 180000
        conn.execute("create extension btree_gist")  # the no-overlap wage constraint
        assert conn.execute("show timezone").fetchone()[0] in ("UTC", "Etc/UTC")


@pytest.mark.parametrize("run", [1, 2])
def test_each_test_gets_a_fresh_empty_database(pg_db, run):
    """Both runs create the same table: sharing a database would collide."""
    with psycopg.connect(pg_db) as conn:
        tables = conn.execute(
            "select count(*) from information_schema.tables where table_schema = 'public'"
        ).fetchone()[0]
        conn.execute("create table scratch (x int)")
    assert tables == 0
