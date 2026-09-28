"""Database backups — one folder, naming and retention for every entry point
(Settings → Backup now and the command palette)."""

import shutil
from datetime import datetime
from pathlib import Path

from ..pg_connection import LOCAL_USER
from ..user_paths import user_dir

KEEP = 10
# SQLite backs up a copy of the database file; Postgres exports the user's data.
_PATTERNS = ("worktimer_*.db", "worktimer_*.json.gz")


def _backups_in(folder: Path) -> list[Path]:
    return [f for pattern in _PATTERNS for f in folder.glob(pattern)]


def backups_dir(db_file: str, user_key: int = LOCAL_USER) -> Path:
    """The user's backups/ next to the database (data/backups for user 1,
    data/users/<key>/backups otherwise) — under Docker inside the mounted
    data/ folder, so backups survive a rebuild of the container."""
    return user_dir(Path(db_file).resolve().parent, user_key) / "backups"


def _adopt_legacy_backups(db_file: str, user_key: int = LOCAL_USER) -> None:
    """Before 5.1.2 Settings saved to backups/ one level above the database:
    the app folder bare-metal, the container's own filesystem under Docker.
    Move any such backups into the current folder so they stay listed and
    pruned. Only the single-user install ever had them."""
    if user_key != LOCAL_USER:
        return
    legacy = Path(db_file).resolve().parent.parent / "backups"
    target = backups_dir(db_file)
    if legacy == target or not legacy.is_dir():
        return
    for f in legacy.glob("worktimer_*.db"):
        target.mkdir(parents=True, exist_ok=True)
        if not (target / f.name).exists():
            shutil.move(str(f), str(target / f.name))


def prune_backups(folder: Path, keep: int = KEEP) -> None:
    """Keep only the newest `keep` backups; delete the rest."""
    files = sorted(
        _backups_in(folder),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups(db_file: str, user_key: int = LOCAL_USER) -> list[Path]:
    """The user's backups, newest first."""
    _adopt_legacy_backups(db_file, user_key)
    folder = backups_dir(db_file, user_key)
    return sorted(_backups_in(folder), key=lambda f: f.name, reverse=True) if folder.exists() else []


def create_backup(db, db_file: str) -> Path:
    """A backup from the data layer (SQLite: a consistent copy of the file;
    Postgres: the user's data) into the user's folder, then prune it to the
    newest KEEP. Blocking — run it in a thread."""
    user_key = getattr(db, "user_key", LOCAL_USER)
    _adopt_legacy_backups(db_file, user_key)
    folder = backups_dir(db_file, user_key)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"worktimer_{datetime.now():%Y-%m-%d_%H%M%S}{db.BACKUP_SUFFIX}"
    db.backup_to(str(dest))
    prune_backups(folder)
    return dest
