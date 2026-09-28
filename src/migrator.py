"""Migrations for the v6 Postgres schema.

Migrations are numbered SQL files in migrations/ — NNNN_short_name.sql —
applied in order, each in its own transaction, and recorded in the
schema_migrations table with a checksum of the file.

The runner stops with a MigrationError rather than guess when:

* a .sql file isn't named NNNN_name.sql, or two files share a number;
* an applied file has been edited since it ran (checksum mismatch) — change
  the schema with a new migration instead;
* an applied file is missing from the directory;
* an unapplied file is numbered below the newest applied one (e.g. two
  branches both added the next number) — renumber it.

A session-level advisory lock serialises concurrent runs (two app instances
starting at once). Statements that can't run inside a transaction (CREATE
INDEX CONCURRENTLY and the like) aren't supported.

Command line:  python -m src.migrator   (connects to $DATABASE_URL_ADMIN — the
server's admin role: 0001 provisions the roles; the app's own DATABASE_URL
connects as worktimer_app and can't migrate)
"""

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_LOCK_KEY = 0x576F726B  # arbitrary constant ("Work"); identifies this app's migration lock

_HISTORY_TABLE = """
    create table if not exists schema_migrations (
        version     integer primary key,
        name        text not null,
        checksum    text not null,
        applied_at  timestamptz not null default now()
    )
"""


class MigrationError(RuntimeError):
    """The migrations directory or the database's migration history is not in
    a state the runner can safely continue from."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8-sig")

    @property
    def checksum(self) -> str:
        """sha256 of the file with line endings normalised — a Windows
        checkout (CRLF) and a Linux image (LF) of the same file must agree."""
        text = self.sql.replace("\r\n", "\n")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Every migration in `directory`, in version order. Non-.sql files (a
    README) are ignored; a .sql file with any other name is an error."""
    found: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if not match:
            raise MigrationError(
                f"{path.name}: migration files must be named NNNN_name.sql "
                "(four digits, then lowercase letters, digits and underscores)")
        version = int(match.group(1))
        if version in found:
            raise MigrationError(
                f"{path.name} and {found[version].path.name} share version {version:04d}")
        found[version] = Migration(version, match.group(2), path)
    return [found[v] for v in sorted(found)]


def _verify(migrations: list[Migration], history: dict[int, str]) -> None:
    """Check the directory against what the database has already applied."""
    on_disk = {m.version: m for m in migrations}
    for version, checksum in sorted(history.items()):
        migration = on_disk.get(version)
        if migration is None:
            raise MigrationError(
                f"migration {version:04d} was applied but its file is missing")
        if migration.checksum != checksum:
            raise MigrationError(
                f"{migration.path.name} was edited after it was applied — "
                "revert it and add a new migration instead")
    newest = max(history, default=-1)
    for migration in migrations:
        if migration.version not in history and migration.version < newest:
            raise MigrationError(
                f"{migration.path.name} is numbered below the newest applied "
                f"migration ({newest:04d}) — renumber it")


def migrate(conninfo: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every pending migration in order; return the applied file names."""
    migrations = discover(directory)
    applied: list[str] = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (_LOCK_KEY,))
        try:
            conn.execute(_HISTORY_TABLE)
            history = dict(conn.execute("select version, checksum from schema_migrations"))
            _verify(migrations, history)
            for migration in migrations:
                if migration.version in history:
                    continue
                try:
                    with conn.transaction():
                        conn.execute(migration.sql)
                        conn.execute(
                            "insert into schema_migrations (version, name, checksum) "
                            "values (%s, %s, %s)",
                            (migration.version, migration.name, migration.checksum),
                        )
                except psycopg.Error as e:
                    raise MigrationError(f"{migration.path.name} failed: {e}") from e
                applied.append(migration.path.name)
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return applied


def main() -> int:
    conninfo = os.environ.get("DATABASE_URL_ADMIN")
    if not conninfo:
        print("Set DATABASE_URL_ADMIN to the database to migrate, as its admin role.",
              file=sys.stderr)
        return 2
    try:
        applied = migrate(conninfo)
    except MigrationError as e:
        print(f"Migration stopped: {e}", file=sys.stderr)
        return 1
    print("\n".join(f"applied {name}" for name in applied) or "database is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
