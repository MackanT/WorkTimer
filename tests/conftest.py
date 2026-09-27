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


@pytest.fixture
def db(tmp_path, null_logger):
    """A fresh, initialized Database on a temp-file SQLite DB.

    Closed in teardown so the file lock is released before pytest cleans tmp_path
    (Windows otherwise can't remove an open .db).
    """
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
