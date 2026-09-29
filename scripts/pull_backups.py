"""Copies the server's nightly database backups to this PC — off the server,
so losing it doesn't take the backups along (docs/staging.md).

    uv run python scripts/pull_backups.py [--host worktimer] [--to FOLDER] [--keep 30]

Only dumps not already in FOLDER are copied (a OneDrive folder adds a cloud
copy); the newest --keep stay. Safe to run any time, e.g. from Task
Scheduler. Needs the ssh/scp client and the server's `worktimer` SSH entry.
A dump restores with pg_restore — see scripts/pg_backup.sh.
"""

import argparse
import subprocess
import sys
from pathlib import Path

REMOTE_DIR = "/opt/worktimer/backups-pg"
PATTERN = "worktimer_*.dump"


def to_fetch(remote_names: list[str], folder: Path) -> list[str]:
    """The server's dumps not yet in `folder`, oldest first."""
    return sorted(n for n in remote_names if not (folder / n).exists())


def prune(folder: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` dumps (names sort by date); returns
    what was deleted."""
    old = sorted(folder.glob(PATTERN))[:-keep] if keep > 0 else []
    for f in old:
        f.unlink()
    return old


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="worktimer", help="the ssh host (~/.ssh/config)")
    parser.add_argument("--to", default=str(Path.home() / "WorkTimer-backups"),
                        help="the local folder for the copies")
    parser.add_argument("--keep", type=int, default=30, help="how many dumps to keep here")
    args = parser.parse_args()

    listing = subprocess.run(["ssh", args.host, f"ls -1 {REMOTE_DIR}/{PATTERN}"],
                             capture_output=True, text=True)
    if listing.returncode:
        print(f"could not list the server's backups: {listing.stderr.strip()}", file=sys.stderr)
        return 1
    remote = [Path(line.strip()).name for line in listing.stdout.splitlines() if line.strip()]

    folder = Path(args.to)
    folder.mkdir(parents=True, exist_ok=True)
    fetched = []
    for name in to_fetch(remote, folder):
        part = folder / f"{name}.part"  # renamed once complete: no half-copied dump
        subprocess.run(["scp", "-q", f"{args.host}:{REMOTE_DIR}/{name}", str(part)], check=True)
        part.replace(folder / name)
        fetched.append(name)
    removed = prune(folder, args.keep)

    kept = sorted(folder.glob(PATTERN))
    print(f"{len(fetched)} new, {len(removed)} removed, {len(kept)} kept in {folder}")
    if kept:
        print(f"newest: {kept[-1].name} ({kept[-1].stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
