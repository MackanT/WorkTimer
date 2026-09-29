"""scripts/pg_backup.sh, run for real with a stand-in pg_dump and clock: what
a backup holds, what it leaves out, and which backups stay."""

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pg_backup.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not (shutil.which("sh") and shutil.which("tar")),
    reason="runs the backup service's shell script: needs sh and GNU tar")


@pytest.fixture
def server(tmp_path):
    """The backup service's view: /data (the app's files), /backups, and a
    pg_dump and date that answer from FAKE_STAMP."""
    bin_dir, data, backups = tmp_path / "bin", tmp_path / "data", tmp_path / "backups"
    for folder in (bin_dir, data, backups):
        folder.mkdir()
    (bin_dir / "pg_dump").write_text(
        '#!/bin/sh\n'
        '[ -z "${FAKE_DUMP_FAILS:-}" ] || exit 1\n'
        'for a; do case $a in --file=*) f=${a#--file=};; esac; done\n'
        'printf %s "$FAKE_STAMP" > "$f"\n')
    (bin_dir / "date").write_text('#!/bin/sh\nprintf "%s\\n" "$FAKE_STAMP"\n')
    for shim in bin_dir.iterdir():
        shim.chmod(0o755)
    files = {
        "notes/plan.md": "# Plan", "notes/plan_assets/i.png": "png",
        "config/time_settings.yml": "rounding_minutes: 15", "OFFICIAL": "",
        "users/3/notes/a.md": "# A", "users/3/config/devops_tags.yml": "tags: []",
        ".nicegui/storage-general.json": "{}",
        ".pat_key": "SECRET", ".storage_secret": "SECRET", "users/3/.pat_key": "SECRET",
        "import/worktimer.db": "transient", "users/3/backups/worktimer_old.db": "export",
    }
    for name, content in files.items():
        (data / name).parent.mkdir(parents=True, exist_ok=True)
        (data / name).write_text(content)

    def run(stamp, **env):
        return subprocess.run(
            ["sh", str(SCRIPT), "--once"], capture_output=True, text=True,
            env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                 "BACKUP_DIR": str(backups), "BACKUP_DATA_DIR": str(data),
                 "FAKE_STAMP": stamp, **env})

    return backups, run


def _names(folder: Path, pattern: str) -> list[str]:
    return sorted(p.name for p in folder.glob(pattern))


def test_a_backup_is_the_database_and_the_files_without_secrets(server):
    backups, run = server

    result = run("2026-09-29_120000")

    assert result.returncode == 0, result.stderr
    assert (backups / "worktimer_2026-09-29_120000.dump").read_text() == "2026-09-29_120000"
    with tarfile.open(backups / "files_2026-09-29_120000.tar.gz") as tar:
        members = {m.name.removeprefix("./") for m in tar.getmembers() if m.isfile()}
    assert members == {"notes/plan.md", "notes/plan_assets/i.png", "config/time_settings.yml",
                       "OFFICIAL", "users/3/notes/a.md", "users/3/config/devops_tags.yml",
                       ".nicegui/storage-general.json"}
    assert _names(backups / "monthly", "*") == ["files_2026-09.tar.gz", "worktimer_2026-09.dump"]
    assert not list(backups.rglob("*.partial"))


def test_the_months_first_backup_is_the_one_kept_for_the_month(server):
    backups, run = server

    for stamp in ("2026-09-29_120000", "2026-09-30_120000", "2026-10-01_120000"):
        assert run(stamp).returncode == 0

    monthly = backups / "monthly"
    assert (monthly / "worktimer_2026-09.dump").read_text() == "2026-09-29_120000"
    assert (monthly / "worktimer_2026-10.dump").read_text() == "2026-10-01_120000"


def test_the_newest_backups_stay(server):
    backups, run = server

    for stamp in ("2026-08-30_120000", "2026-09-29_120000", "2026-10-01_120000"):
        assert run(stamp, BACKUP_KEEP="2", BACKUP_KEEP_MONTHLY="2").returncode == 0

    assert _names(backups, "worktimer_*.dump") == [
        "worktimer_2026-09-29_120000.dump", "worktimer_2026-10-01_120000.dump"]
    assert _names(backups, "files_*.tar.gz") == [
        "files_2026-09-29_120000.tar.gz", "files_2026-10-01_120000.tar.gz"]
    assert _names(backups / "monthly", "worktimer_*") == [
        "worktimer_2026-09.dump", "worktimer_2026-10.dump"]
    assert _names(backups / "monthly", "files_*") == ["files_2026-09.tar.gz", "files_2026-10.tar.gz"]


def test_a_failed_dump_is_reported_and_leaves_nothing_behind(server):
    backups, run = server

    result = run("2026-09-29_120000", FAKE_DUMP_FAILS="1")

    assert result.returncode == 1 and "backup FAILED" in result.stderr
    assert _names(backups, "worktimer_*") == [] and _names(backups / "monthly", "worktimer_*") == []
    assert _names(backups, "files_*") == ["files_2026-09-29_120000.tar.gz"]  # the files still
