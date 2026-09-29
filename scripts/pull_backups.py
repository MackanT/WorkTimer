"""Copies the server's nightly backups — database dumps and archives of the
notes and settings — to this PC, off the server, so losing it doesn't take
the backups along (docs/staging.md).

    uv run python scripts/pull_backups.py [--host worktimer] [--to FOLDER]
        [--keep 30] [--keep-monthly 0]

Only backups not already in FOLDER are copied (a OneDrive folder adds a
cloud copy); the newest --keep of each kind stay, and in FOLDER/monthly the
newest --keep-monthly (0: all). Safe to run any time, e.g. from Task
Scheduler. Needs the ssh/scp client and the server's `worktimer` SSH entry.
A dump restores with pg_restore — see scripts/pg_backup.sh.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

REMOTE_DIR = "/opt/worktimer/backups-pg"
PATTERNS = ("worktimer_*.dump", "files_*.tar.gz")
BACKUP_NAME = re.compile(r"(monthly/)?(worktimer_[0-9_-]+\.dump|files_[0-9_-]+\.tar\.gz)")


def backup_names(listing: str) -> list[str]:
    """The backups in the server's `find .` listing, relative to its backup
    folder — anything else (a half-written .partial, a stray file) left out."""
    names = (line.strip().removeprefix("./") for line in listing.splitlines())
    return [n for n in names if BACKUP_NAME.fullmatch(n)]


def to_fetch(remote_names: list[str], folder: Path) -> list[str]:
    """The server's dumps not yet in `folder`, oldest first."""
    return sorted(n for n in remote_names if not (folder / n).exists())


def prune(folder: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` backups of each kind (names sort by
    date); returns what was deleted."""
    old = [f for p in PATTERNS for f in sorted(folder.glob(p))[:-keep]] if keep > 0 else []
    for f in old:
        f.unlink()
    return old


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="worktimer", help="the ssh host (~/.ssh/config)")
    parser.add_argument("--to", default=str(Path.home() / "WorkTimer-backups"),
                        help="the local folder for the copies")
    parser.add_argument("--keep", type=int, default=30, help="how many of each kind to keep here")
    parser.add_argument("--keep-monthly", type=int, default=0,
                        help="how many monthly ones to keep here (0: all)")
    args = parser.parse_args()

    listing = subprocess.run(["ssh", args.host, f"cd {REMOTE_DIR} && find . -maxdepth 2 -type f"],
                             capture_output=True, text=True)
    if listing.returncode:
        print(f"could not list the server's backups: {listing.stderr.strip()}", file=sys.stderr)
        return 1
    remote = backup_names(listing.stdout)

    folder = Path(args.to)
    fetched = []
    for name in to_fetch(remote, folder):
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(f"{target.name}.part")  # renamed once complete: no half copy
        subprocess.run(["scp", "-q", f"{args.host}:{REMOTE_DIR}/{name}", str(part)], check=True)
        part.replace(target)
        fetched.append(name)
    removed = prune(folder, args.keep) + prune(folder / "monthly", args.keep_monthly)

    kept = [f for p in PATTERNS for f in (*folder.glob(p), *folder.glob(f"monthly/{p}"))]
    print(f"{len(fetched)} new, {len(removed)} removed, {len(kept)} kept in {folder}")
    for pattern in PATTERNS:
        newest = sorted(folder.glob(pattern))[-1:]
        for f in newest:
            print(f"newest: {f.name} ({f.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
