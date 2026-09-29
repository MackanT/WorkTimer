"""Postgres connection layer (v6 phase 1.4).

Every statement against user data runs inside ``Pools.transaction(user_key)``:
BEGIN → the transaction's user set → work → COMMIT, or ROLLBACK on any error.
Row-level security compares every user-data row with that user, so tenancy is
decided here and nowhere else — never at call sites.

The user is set with ``SET LOCAL app.user_id``: it ends with the transaction,
so a pooled connection can't carry one user into the next user's transaction.
Outside a transaction it would silently do nothing — which is why nothing here
hands out a bare connection. (No role may call set_config(), which could
change it from inside a query — migration 0002.)

Read-only transactions — the query editor's users' own SELECTs — run on
worktimer_readonly, in a READ ONLY transaction, optionally with a statement
timeout and the user's time zone.

Config: DATABASE_URL connects as worktimer_app; DATABASE_URL_READONLY as
worktimer_readonly (the query editor, phase 3). Migrations run separately, as
the admin role (src/migrator.py, DATABASE_URL_ADMIN).
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool

LOCAL_USER = 1  # the single-user install's only user (seeded by migration 0001)


class ConfigError(RuntimeError):
    """A Postgres connection setting the caller needs is missing."""


@dataclass(frozen=True)
class PgConfig:
    url: str
    readonly_url: str | None = None

    @classmethod
    def from_env(cls) -> "PgConfig":
        url = os.getenv("DATABASE_URL")
        if not url:
            raise ConfigError("Set DATABASE_URL to the database, as the worktimer_app role.")
        return cls(url, os.getenv("DATABASE_URL_READONLY") or None)


def describe_database(sqlite_path: str) -> str:
    """Which database the app runs on, for the startup banner — never the
    password."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return f"SQLite {sqlite_path}"
    from psycopg.conninfo import conninfo_to_dict

    info = conninfo_to_dict(url)
    return (f"Postgres {info.get('user', '?')}@{info.get('host', 'localhost')}:"
            f"{info.get('port', 5432)}/{info.get('dbname', '?')}")


def _user_setting(user_key) -> str:
    """The value for app.user_id. Anything but a positive int is refused here,
    before a connection is taken: a wrong key must never become a query."""
    if isinstance(user_key, bool) or not isinstance(user_key, int) or user_key < 1:
        raise ValueError(f"a transaction needs a user key (a positive int), not {user_key!r}")
    return str(user_key)


def _configure(conn: psycopg.Connection) -> None:
    # Stored and computed in UTC; local time is presentation only (§4).
    conn.execute("set time zone 'UTC'")


class Pools:
    """The app's connection pools: worktimer_app, and worktimer_readonly when
    configured. Thread-safe — Database methods run in worker threads."""

    def __init__(self, config: PgConfig, min_size: int = 1, max_size: int = 10):
        def pool(url: str, name: str) -> ConnectionPool:
            return ConnectionPool(
                url, name=name, min_size=min_size, max_size=max_size,
                kwargs={"autocommit": True}, configure=_configure,
                check=ConnectionPool.check_connection, open=True,
            )

        self._app = pool(config.url, "worktimer_app")
        self._readonly = (
            pool(config.readonly_url, "worktimer_readonly") if config.readonly_url else None
        )

    @contextmanager
    def transaction(self, user_key: int, *, readonly: bool = False,
                    timeout_ms: int | None = None,
                    timezone: str | None = None) -> Iterator[psycopg.Connection]:
        """One transaction as `user_key`; commits on success, rolls back on
        error. `timeout_ms` caps each statement; `timezone` is the session's
        zone for the transaction."""
        setup = [sql.SQL("set local app.user_id = {}").format(sql.Literal(_user_setting(user_key)))]
        if readonly:
            if self._readonly is None:
                raise ConfigError("Set DATABASE_URL_READONLY for read-only transactions.")
            setup.insert(0, sql.SQL("set transaction read only"))
        if timeout_ms is not None:
            setup.append(sql.SQL("set local statement_timeout = {}").format(sql.Literal(int(timeout_ms))))
        if timezone is not None:
            ZoneInfo(timezone)  # an unknown zone fails here, not in the database
            setup.append(sql.SQL("set local time zone {}").format(sql.Literal(timezone)))
        pool = self._readonly if readonly else self._app
        with pool.connection() as conn, conn.transaction():
            for statement in setup:
                conn.execute(statement)
            yield conn

    def sign_in(self, bk_user: str, email: str | None = None, name: str | None = None,
                claim_local: bool = False) -> int:
        """The user key for a verified identity (its IdP subject), creating the
        user on a first sign-in — app_sign_in (migrations 0003, 0004), the only
        way a user is added. With `claim_local` (the install's owner), a first
        sign-in takes over user 1 while that is still 'local'. Refused for
        'local', a blank subject or a disabled user."""
        with self._app.connection() as conn:
            return conn.execute("select app_sign_in(%s, %s, %s, %s)",
                                (bk_user, email, name, claim_local)).fetchone()[0]

    def signed_in_users(self) -> int:
        """How many users have signed in — everyone but 'local'."""
        with self._app.connection() as conn:
            return conn.execute("select app_signed_in_users()").fetchone()[0]

    def close(self) -> None:
        self._app.close()
        if self._readonly is not None:
            self._readonly.close()
