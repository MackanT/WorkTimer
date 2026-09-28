"""Postgres connection layer (v6 phase 1.4).

Every statement against user data runs inside ``Pools.transaction(user_key)``:
BEGIN → the transaction's user set → work → COMMIT, or ROLLBACK on any error.
Row-level security compares every user-data row with that user, so tenancy is
decided here and nowhere else — never at call sites.

The user is set with ``set_config('app.user_id', …, true)``: SET LOCAL
semantics, so it ends with the transaction and a pooled connection can't carry
one user into the next user's transaction. Outside a transaction it would
silently do nothing — which is why nothing here hands out a bare connection.

Config: DATABASE_URL connects as worktimer_app; DATABASE_URL_READONLY as
worktimer_readonly (the query editor, phase 3). Migrations run separately, as
the admin role (src/migrator.py, DATABASE_URL_ADMIN).
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
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
    def transaction(self, user_key: int, *, readonly: bool = False) -> Iterator[psycopg.Connection]:
        """One transaction as `user_key`; commits on success, rolls back on error."""
        setting = _user_setting(user_key)
        if readonly and self._readonly is None:
            raise ConfigError("Set DATABASE_URL_READONLY for read-only transactions.")
        pool = self._readonly if readonly else self._app
        with pool.connection() as conn, conn.transaction():
            conn.execute("select set_config('app.user_id', %s, true)", (setting,))
            yield conn

    def close(self) -> None:
        self._app.close()
        if self._readonly is not None:
            self._readonly.close()
