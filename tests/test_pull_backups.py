"""scripts/pull_backups.py: which of the server's dumps to copy, and which
local copies to let go."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "pull_backups", Path(__file__).resolve().parents[1] / "scripts" / "pull_backups.py")
pull_backups = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pull_backups)


def _dump(folder, day):
    path = folder / f"worktimer_2026-09-{day:02d}_104343.dump"
    path.write_bytes(b"dump")
    return path


def test_only_dumps_not_here_yet_are_copied(tmp_path):
    _dump(tmp_path, 28)
    remote = ["worktimer_2026-09-30_104343.dump", "worktimer_2026-09-28_104343.dump",
              "worktimer_2026-09-29_104343.dump"]

    assert pull_backups.to_fetch(remote, tmp_path) == [
        "worktimer_2026-09-29_104343.dump", "worktimer_2026-09-30_104343.dump"]


def test_the_newest_are_kept(tmp_path):
    dumps = [_dump(tmp_path, day) for day in range(1, 6)]
    (tmp_path / "notes.txt").write_text("not a dump")

    removed = pull_backups.prune(tmp_path, keep=3)

    assert removed == dumps[:2]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [d.name for d in dumps[2:]] + ["notes.txt"])
    assert pull_backups.prune(tmp_path, keep=0) == []  # 0: keep everything
