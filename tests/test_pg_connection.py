"""The connection layer (src/pg_connection.py, v6 phase 1.4): pools logged in
as the app's own roles, and the one place a transaction's user is set.

Unlike tests/test_schema_v1.py (an admin session switching role), these log in
as worktimer_app and worktimer_readonly for real — as the app will.
"""

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import errors  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402

from src.pg_connection import LOCAL_USER, ConfigError, PgConfig, Pools  # noqa: E402

pytestmark = pytest.mark.postgres


@pytest.fixture
def config(pg_schema_db, pg_logins):
    return PgConfig(
        make_conninfo(pg_schema_db, user="worktimer_app", password=pg_logins["worktimer_app"]),
        make_conninfo(pg_schema_db, user="worktimer_readonly",
                      password=pg_logins["worktimer_readonly"]),
    )


@pytest.fixture
def pools(config):
    """One connection per pool, so every transaction reuses the same session —
    what makes a leaked setting visible."""
    p = Pools(config, min_size=1, max_size=1)
    yield p
    p.close()


@pytest.fixture
def user2(pg_schema_db):
    with psycopg.connect(pg_schema_db) as admin:
        return admin.execute("insert into users (bk_user) values ('second') "
                             "returning key_user").fetchone()[0]


def _names(pools, user, **kw):
    with pools.transaction(user, **kw) as conn:
        return [r[0] for r in conn.execute("select customer_name from customers order by 1")]


def test_writes_and_reads_go_through_the_pool_with_rls_on(pools, user2):
    with pools.transaction(LOCAL_USER) as conn:
        key = conn.execute("insert into customers (customer_name) values ('Acme') "
                           "returning key_customer").fetchone()[0]
        conn.execute("insert into customer_wages (fk_customer, wage, valid_from) "
                     "values (%s, 1000, '2026-01-01')", (key,))
    with pools.transaction(user2) as conn:
        conn.execute("insert into customers (customer_name) values ('Beta')")

    with pools.transaction(LOCAL_USER) as conn:
        rows = conn.execute("select c.customer_name, c.fk_user, c.created_by, w.wage "
                            "from customers c join customer_wages w "
                            "on w.fk_customer = c.key_customer").fetchall()
    assert rows == [("Acme", 1, 1, 1000)]
    assert _names(pools, user2) == ["Beta"]


def test_the_pools_log_in_as_the_apps_own_roles(pools):
    for readonly, role in ((False, "worktimer_app"), (True, "worktimer_readonly")):
        with pools.transaction(LOCAL_USER, readonly=readonly) as conn:
            assert conn.execute("select session_user, current_user").fetchone() == (role, role)
            for other in ("worktimer_owner", "postgres"):
                with pytest.raises(errors.InsufficientPrivilege):
                    with conn.transaction():
                        conn.execute(f"set local role {other}")


def test_the_users_setting_ends_with_its_transaction(pools, user2):
    """Same pooled session throughout: user 1's id must not reach the next
    transaction — or anything run outside one."""
    with pools.transaction(LOCAL_USER) as conn:
        conn.execute("insert into customers (customer_name) values ('Acme')")
        pid = conn.execute("select pg_backend_pid()").fetchone()[0]
        assert conn.execute("select current_setting('app.user_id')").fetchone()[0] == "1"

    with pools.transaction(user2) as conn:
        assert conn.execute("select pg_backend_pid()").fetchone()[0] == pid
        assert conn.execute("select count(*) from customers").fetchone()[0] == 0

    with pools._app.connection() as conn:  # a bare session: exactly what the API never hands out
        assert conn.execute("select pg_backend_pid()").fetchone()[0] == pid
        assert conn.execute("select current_setting('app.user_id', true)").fetchone()[0] in ("", None)
        assert conn.execute("select count(*) from customers").fetchone()[0] == 0


def test_an_error_rolls_the_whole_transaction_back(pools):
    with pytest.raises(RuntimeError):
        with pools.transaction(LOCAL_USER) as conn:
            conn.execute("insert into customers (customer_name) values ('Half-done')")
            raise RuntimeError("the work failed")
    with pytest.raises(errors.UniqueViolation):
        with pools.transaction(LOCAL_USER) as conn:
            conn.execute("insert into customers (customer_name) values ('Twice')")
            conn.execute("insert into customers (customer_name) values ('Twice')")

    assert _names(pools, LOCAL_USER) == []
    with pools.transaction(LOCAL_USER) as conn:  # the pool recovered the session
        conn.execute("insert into customers (customer_name) values ('After')")
    assert _names(pools, LOCAL_USER) == ["After"]


def test_readonly_transactions_read_their_user_and_write_nothing(pools, user2):
    with pools.transaction(LOCAL_USER) as conn:
        conn.execute("insert into customers (customer_name) values ('Acme')")
        conn.execute("insert into trackers (tracker_name, pat_token) values ('T', 'enc:x')")

    assert _names(pools, LOCAL_USER, readonly=True) == ["Acme"]
    assert _names(pools, user2, readonly=True) == []
    with pools.transaction(LOCAL_USER, readonly=True) as conn:
        for statement in ("insert into customers (customer_name) values ('No')",
                          "delete from customers",
                          "select pat_token from trackers"):
            # A READ ONLY transaction, on a role without write privileges.
            with pytest.raises((errors.ReadOnlySqlTransaction, errors.InsufficientPrivilege)):
                with conn.transaction():
                    conn.execute(statement)


def test_the_app_roles_own_login_cannot_bypass_rls(config, pg_schema_db):
    with psycopg.connect(pg_schema_db) as admin:
        admin.execute("insert into customers (fk_user, customer_name) values (1, 'Acme')")
    with psycopg.connect(config.url, autocommit=True) as conn:
        assert conn.execute("select count(*) from customers").fetchone()[0] == 0
        conn.execute("set row_security = off")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("select count(*) from customers")


@pytest.mark.parametrize("key", [0, -1, None, "1", 1.0, True])
def test_a_bad_user_key_never_reaches_the_database(pools, key):
    with pytest.raises(ValueError, match="user key"):
        with pools.transaction(key):
            pass


def test_read_only_transactions_carry_their_limits(pools):
    with pools.transaction(LOCAL_USER, readonly=True, timeout_ms=1234,
                           timezone="America/New_York") as conn:
        settings = conn.execute(
            "select current_setting('transaction_read_only'), "
            "current_setting('statement_timeout'), current_setting('TimeZone')").fetchone()
    assert settings == ("on", "1234ms", "America/New_York")
    with pools.transaction(LOCAL_USER) as conn:  # none of it outlives the transaction
        assert conn.execute("select current_setting('statement_timeout'), "
                            "current_setting('TimeZone')").fetchone() == ("0", "UTC")


def test_an_unknown_time_zone_fails_before_the_database(pools):
    with pytest.raises(Exception, match="Mars/Olympus"):
        with pools.transaction(LOCAL_USER, readonly=True, timezone="Mars/Olympus"):
            pass


def test_connections_compute_in_utc(pools):
    with pools.transaction(LOCAL_USER) as conn:
        assert conn.execute("show timezone").fetchone()[0] == "UTC"


def test_a_readonly_transaction_needs_its_own_url(config):
    p = Pools(PgConfig(config.url))
    try:
        with pytest.raises(ConfigError, match="DATABASE_URL_READONLY"):
            with p.transaction(LOCAL_USER, readonly=True):
                pass
    finally:
        p.close()


def test_config_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_READONLY", raising=False)
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        PgConfig.from_env()

    monkeypatch.setenv("DATABASE_URL", "postgresql://app@db/worktimer")
    monkeypatch.setenv("DATABASE_URL_READONLY", "")  # compose passes unset variables as empty
    assert PgConfig.from_env() == PgConfig("postgresql://app@db/worktimer", None)
    monkeypatch.setenv("DATABASE_URL_READONLY", "postgresql://ro@db/worktimer")
    assert PgConfig.from_env().readonly_url == "postgresql://ro@db/worktimer"
