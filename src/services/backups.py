"""Database backups — one folder, naming and retention for every entry point
(Settings → Backup now and the command palette)."""

import shutil
from datetime import datetime
from pathlib import Path

KEEP = 10
# SQLite backs up a copy of the database file; Postgres exports the user's data.
_PATTERNS = ("worktimer_*.db", "worktimer_*.json.gz")


def _backups_in(folder: Path) -> list[Path]:
    return [f for pattern in _PATTERNS for f in folder.glob(pattern)]


def backups_dir(db_file: str) -> Path:
    """backups/ next to the database — under Docker that is inside the mounted
    data/ folder, so backups survive a rebuild of the container."""
    return Path(db_file).resolve().parent / "backups"


def _adopt_legacy_backups(db_file: str) -> None:
    """Before 5.1.2 Settings saved to backups/ one level above the database:
    the app folder bare-metal, the container's own filesystem under Docker.
    Move any such backups into the current folder so they stay listed and
    pruned."""
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


def list_backups(db_file: str) -> list[Path]:
    """Backups newest first."""
    _adopt_legacy_backups(db_file)
    folder = backups_dir(db_file)
    return sorted(_backups_in(folder), key=lambda f: f.name, reverse=True) if folder.exists() else []


def create_backup(db, db_file: str) -> Path:
    """A backup from the data layer (SQLite: a consistent copy of the file;
    Postgres: the user's data), then prune to the newest KEEP. Blocking — run
    it in a thread."""
    _adopt_legacy_backups(db_file)
    folder = backups_dir(db_file)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"worktimer_{datetime.now():%Y-%m-%d_%H%M%S}{db.BACKUP_SUFFIX}"
    db.backup_to(str(dest))
    prune_backups(folder)
    return dest
