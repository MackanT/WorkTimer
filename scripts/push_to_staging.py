"""Phase 5's weekly import, from your PC (docs/staging.md).

A consistent snapshot of the live 5.x database (SQLite's backup API — safe
while WorkTimer runs), copied to the staging server over SSH, imported there
over the account (scripts/staging.sh import), and the report printed.

    uv run python scripts/push_to_staging.py [--host worktimer] [--db data/worktimer.db]

Needs the ssh/scp client and the server set up per docs/staging.md. The exit
code is the import's: 0 when every customer and month matches.
"""

import argparse
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REMOTE_DIR = "/opt/worktimer"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="worktimer", help="the ssh host (~/.ssh/config)")
    parser.add_argument("--db", default="data/worktimer.db", help="the live 5.x database")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "worktimer.db"
        source = sqlite3.connect(f"file:{Path(args.db).resolve().as_posix()}?mode=ro", uri=True)
        target = sqlite3.connect(snapshot)
        source.backup(target)
        source.close()
        target.close()
        print(f"snapshot: {snapshot.stat().st_size:,} bytes")
        subprocess.run(["ssh", args.host, f"mkdir -p {REMOTE_DIR}/data-pg/import"], check=True)
        subprocess.run(["scp", "-q", str(snapshot),
                        f"{args.host}:{REMOTE_DIR}/data-pg/import/worktimer.db"], check=True)
    return subprocess.run(["ssh", args.host, f"bash {REMOTE_DIR}/scripts/staging.sh import"]).returncode


if __name__ == "__main__":
    sys.exit(main())
