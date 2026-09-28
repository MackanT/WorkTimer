"""The query editor on Postgres (v6 Phase 3): users' own SQL runs on the
read-only role, for their user only, as one SELECT, in a READ ONLY
transaction, capped in time and rows. The role and the database are the
guards — the text check only words the refusal, so several tests go past it
on purpose.
"""

import time

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import errors  # noqa: E402

from src import helpers  # noqa: E402
from src.pg_database import PgDatabase  # noqa: E402

pytestmark = [pytest.mark.backends("postgres"), pytest.mark.postgres]


def _acme_with_an_entry(db, day="2026-09-01"):
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    row = db.get_data_input_list().iloc[0]
    db.insert_manual_time_row(int(row.customer_id), int(row.project_id),
                              f"{day} 09:00", f"{day} 10:30", comment="work")


def test_a_users_query_sees_only_their_rows(db, pg_schema_db):
    _acme_with_an_entry(db)
    with psycopg.connect(pg_schema_db) as admin:
        admin.execute("insert into users (bk_user) values ('second')")
        admin.execute("insert into customers (fk_user, customer_name) values (2, 'Theirs')")

    df = db.run_user_query("select customer_name from customers")

    assert df["customer_name"].tolist() == ["Acme"]


@pytest.mark.parametrize("query", [
    "delete from customers",
    "update customers set color = 'x'",
    "insert into tasks (title) values ('x')",
    "create table planted (x int)",
    "drop table customers",
])
def test_writes_are_refused_with_a_readable_message(db, query):
    with pytest.raises(ValueError, match="Only SELECT"):
        db.run_user_query(query)


def test_a_write_past_the_text_check_is_stopped_by_the_database(db):
    """A data-modifying WITH starts like a SELECT."""
    _acme_with_an_entry(db)

    with pytest.raises((errors.ReadOnlySqlTransaction, errors.InsufficientPrivilege)):
        db.run_user_query("with gone as (delete from customers returning *) select * from gone")

    assert db.get_current_customer_names()["customer_name"].tolist() == ["Acme"]


def test_one_statement_at_a_time(db):
    with pytest.raises(ValueError, match="one statement"):
        db.run_user_query("select 1; delete from customers")
    # Semicolons inside strings and comments are just text.
    assert db.run_user_query("select ';' as s -- ; not a statement\n")["s"].tolist() == [";"]


def test_the_database_refuses_a_second_statement_too(db, monkeypatch):
    """Even if the text check missed one, the prepared statement can't hold two."""
    monkeypatch.setattr("src.pg_database._user_select", lambda query: query)

    with pytest.raises(errors.SyntaxError, match="multiple commands"):
        db.run_user_query("select 1; select 2")


def test_a_query_cannot_switch_to_another_user(db, pg_schema_db):
    """Row-level security compares rows with app.user_id; no query may move it."""
    _acme_with_an_entry(db)
    with psycopg.connect(pg_schema_db) as admin:
        admin.execute("insert into users (bk_user) values ('second')")
        admin.execute("insert into customers (fk_user, customer_name) values (2, 'Theirs')")

    with pytest.raises(errors.InsufficientPrivilege):  # migration 0002
        db.run_user_query("select set_config('app.user_id', '2', true)")
    # pg_settings' update rule is closed too (0002); inside a WITH it doesn't
    # even run — either way the query still sees only its own user's rows.
    df = db.run_user_query("with x as (update pg_settings set setting = '2' "
                           "where name = 'app.user_id') select customer_name from customers")
    assert df["customer_name"].tolist() == ["Acme"]


def test_long_queries_are_stopped(db, monkeypatch):
    monkeypatch.setattr(PgDatabase, "USER_QUERY_TIMEOUT_MS", 300)
    started = time.monotonic()

    with pytest.raises(errors.QueryCanceled):
        db.run_user_query("select pg_sleep(5)")

    assert time.monotonic() - started < 4


def test_results_are_capped(db, monkeypatch):
    monkeypatch.setattr(PgDatabase, "USER_QUERY_ROWS", 10)

    capped = db.run_user_query("select g from generate_series(1, 25) g")
    whole = db.run_user_query("select g from generate_series(1, 5) g")

    assert (len(capped), capped.attrs["truncated"]) == (10, True)
    assert (len(whole), whole.attrs["truncated"]) == (5, False)


def test_times_show_in_the_users_zone(db):
    _acme_with_an_entry(db, day="2026-07-01")

    [row] = db.run_user_query(
        "select started_at, current_setting('TimeZone') as tz from time_entries").to_dict("records")

    assert (row["started_at"], row["tz"]) == ("2026-07-01 09:00:00", "Europe/Stockholm")


def test_percent_signs_are_just_text(db):
    assert db.run_user_query("select 'a%b' as x where 'abc' like '%b%'")["x"].tolist() == ["a%b"]


def test_the_syntax_check_plans_without_running(db):
    started = time.monotonic()
    db.check_user_query("select pg_sleep(30)")  # planned, not run
    assert time.monotonic() - started < 5

    with pytest.raises(errors.SyntaxError):
        db.check_user_query("select 1 +")  # a SELECT the server can't parse
    with pytest.raises(ValueError):
        db.check_user_query("selec broken")  # not even a SELECT
    with pytest.raises(ValueError, match="Only SELECT"):
        db.check_user_query("delete from customers")


def test_the_default_queries_run_on_the_v6_schema(db):
    """Refreshed for the user at startup (initialize_db); each runs, and the
    three the row-edit dialog opens from carry their table's key."""
    from datetime import date

    _acme_with_an_entry(db, day=date.today().isoformat())
    saved = dict(zip(db.get_query_list()["query_name"], db.get_query_list()["is_default"]))
    assert {k: saved.get(k) for k in PgDatabase.DEFAULT_QUERIES} == dict.fromkeys(
        PgDatabase.DEFAULT_QUERIES, 1)

    for name, query in PgDatabase.DEFAULT_QUERIES.items():
        df = db.run_user_query(query)
        target = db.ROW_EDIT_TABLES.get(helpers.extract_table_name(query))
        if name in ("time", "customers", "projects"):
            assert target is not None and target[1] in df.columns, name
    assert db.run_user_query(PgDatabase.DEFAULT_QUERIES["time"])["customer_name"].tolist() == ["Acme"]
    weekly = db.run_user_query(PgDatabase.DEFAULT_QUERIES["weekly"]).to_dict("records")
    assert weekly[0] == {"customer_name": "Acme", "project_name": "Build", "hours": 1.5}
