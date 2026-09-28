"""Database backups — one folder, naming and retention for every entry point
(Settings → Backup now and the command palette)."""

import shutil
from datetime import datetime
from pathlib import Path

KEEP = 10


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
    """Keep only the newest `keep` worktimer_*.db backups; delete the rest."""
    files = sorted(
        folder.glob("worktimer_*.db"),
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
    return sorted(folder.glob("worktimer_*.db"), reverse=True) if folder.exists() else []


def create_backup(db, db_file: str) -> Path:
    """A consistent copy of the live database (SQLite online backup), then
    prune to the newest KEEP. Blocking — run it in a thread."""
    _adopt_legacy_backups(db_file)
    folder = backups_dir(db_file)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"worktimer_{datetime.now():%Y-%m-%d_%H%M%S}.db"
    db.backup_to(str(dest))
    prune_backups(folder)
    return dest
