"""Shared pytest fixtures for the WorkTimer regression suite.

Run with:  uv run pytest
"""

import logging
import os
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def null_logger() -> logging.Logger:
    """A quiet logger so Database/engine internals don't spam test output."""
    lg = logging.getLogger("worktimer.tests")
    lg.handlers = [logging.NullHandler()]
    lg.propagate = False
    return lg


def pytest_generate_tests(metafunc):
    """Run `db` tests on every backend their module lists with
    ``pytest.mark.backends("sqlite", "postgres")`` — how the Phase 0
    characterisation tests become the oracle for the Postgres port
    (docs/v6_implementation.md, Phase 2). Unmarked: SQLite only."""
    marker = metafunc.definition.get_closest_marker("backends")
    if marker and "db" in metafunc.fixturenames:
        metafunc.parametrize("db", marker.args, indirect=True)


@pytest.fixture
def db(request, tmp_path, null_logger):
    """A fresh, initialized Database: a temp-file SQLite DB, or — for
    backend "postgres" — the Postgres port on a fresh copy of the v6 schema,
    logged in as worktimer_app for user 1.

    Closed in teardown so the file lock is released before pytest cleans tmp_path
    (Windows otherwise can't remove an open .db).
    """
    if getattr(request, "param", "sqlite") == "postgres":
        from psycopg.conninfo import make_conninfo

        from src.pg_connection import PgConfig, Pools
        from src.pg_database import PgDatabase

        conninfo = request.getfixturevalue("pg_schema_db")
        password = request.getfixturevalue("pg_logins")["worktimer_app"]
        pools = Pools(PgConfig(make_conninfo(conninfo, user="worktimer_app", password=password)),
                      min_size=1, max_size=2)
        database = PgDatabase(pools, null_logger, secrets_dir=str(tmp_path))
    else:
        from src.database import Database

        database = Database(str(tmp_path / "test.db"), null_logger)
    database.initialize_db()
    yield database
    database.close()


# ── Postgres (v6) ───────────────────────────────────────────────────────────
#
# Tests run against the `postgres` service in docker-compose.yml
# (`docker compose up -d postgres`; from Windows with Docker in WSL:
# `wsl docker compose up -d postgres` in the repo). Each test gets its own
# throwaway database on it, so tests share no state and never touch a real
# database. When the server isn't running, Postgres tests are skipped and the
# rest of the suite still runs.

PG_ADMIN_URL = os.getenv(
    "WORKTIMER_TEST_PG_URL",
    "postgresql://postgres:worktimer-dev@127.0.0.1:5432/postgres",
)
PG_TEST_PREFIX = "wt_test_"


def _drop_database(admin, name: str) -> None:
    from psycopg import sql

    admin.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def pg_server() -> str:
    """Admin conninfo for the dev Postgres; skips the test when it's
    unreachable. Also sweeps throwaway databases that a crashed earlier run
    left behind (so two test sessions must not run at the same time)."""
    psycopg = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(PG_ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable — start it with `docker compose up -d postgres` "
                    "(Docker in WSL: `wsl docker compose up -d postgres` in the repo)")
    with admin:
        stale = admin.execute(
            r"select datname from pg_database where datname like %s escape '\'",
            (PG_TEST_PREFIX.replace("_", r"\_") + "%",),
        ).fetchall()
        for (name,) in stale:
            _drop_database(admin, name)
    return PG_ADMIN_URL


@pytest.fixture
def pg_db(pg_server) -> str:
    """Conninfo for a fresh, empty database of its own; dropped afterwards."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    name = f"{PG_TEST_PREFIX}{uuid.uuid4().hex[:12]}"
    with psycopg.connect(pg_server, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    yield make_conninfo(pg_server, dbname=name)
    with psycopg.connect(pg_server, autocommit=True) as admin:
        _drop_database(admin, name)


@pytest.fixture(scope="session")
def pg_schema_template(pg_server) -> str:
    """Name of a database with every migration applied, once per session —
    the template each `pg_schema_db` is cloned from (much faster than
    migrating every time)."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from src.migrator import migrate

    name = f"{PG_TEST_PREFIX}template_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(pg_server, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    migrate(make_conninfo(pg_server, dbname=name))
    yield name
    with psycopg.connect(pg_server, autocommit=True) as admin:
        _drop_database(admin, name)


@pytest.fixture(scope="session")
def pg_logins(pg_server, pg_schema_template) -> dict:
    """Passwords to log in as worktimer_app and worktimer_readonly, random per
    session. Migration 0001 creates the roles NOLOGIN (passwords are deployment
    configuration). Roles are server-wide, so a local compose instance may be
    using them: each gets back exactly its login and password (hash) afterwards."""
    import secrets

    import psycopg
    from psycopg import sql

    passwords = {r: secrets.token_urlsafe(24) for r in ("worktimer_app", "worktimer_readonly")}
    with psycopg.connect(pg_server, autocommit=True) as admin:
        before = {r: admin.execute("select rolcanlogin, rolpassword from pg_authid "
                                   "where rolname = %s", (r,)).fetchone() for r in passwords}
        for role, password in passwords.items():
            admin.execute(sql.SQL("alter role {} login password {}").format(
                sql.Identifier(role), sql.Literal(password)))
    yield passwords
    with psycopg.connect(pg_server, autocommit=True) as admin:
        for role, (could_login, password_hash) in before.items():
            admin.execute(sql.SQL("alter role {} {} password {}").format(
                sql.Identifier(role), sql.SQL("login" if could_login else "nologin"),
                sql.Literal(password_hash)))


def _clone_schema_db(pg_server, template):
    """A new database cloned from the migrated template: (conninfo, drop)."""
    import time

    import psycopg
    from psycopg import errors, sql
    from psycopg.conninfo import make_conninfo

    name = f"{PG_TEST_PREFIX}{uuid.uuid4().hex[:12]}"
    create = sql.SQL("create database {} template {}").format(
        sql.Identifier(name), sql.Identifier(template))
    with psycopg.connect(pg_server, autocommit=True) as admin:
        for attempt in range(50):
            try:
                admin.execute(create)
                break
            except errors.ObjectInUse:  # the template's last session is still closing
                if attempt == 49:
                    raise
                time.sleep(0.1)

    def drop():
        with psycopg.connect(pg_server, autocommit=True) as admin:
            _drop_database(admin, name)

    return make_conninfo(pg_server, dbname=name), drop


@pytest.fixture
def pg_schema_db(pg_server, pg_schema_template) -> str:
    """Conninfo for a fresh database with the full v6 schema; dropped afterwards."""
    conninfo, drop = _clone_schema_db(pg_server, pg_schema_template)
    yield conninfo
    drop()


@pytest.fixture(scope="module")
def pg_schema_db_module(pg_server, pg_schema_template) -> str:
    """The same, shared by one test module."""
    conninfo, drop = _clone_schema_db(pg_server, pg_schema_template)
    yield conninfo
    drop()
