"""Regression (5.1.2): the Docker build context must not carry local state.

`ADD . /app` copies the whole checkout into the image. With only build junk in
.dockerignore, every image held the real database, the key that decrypts its
tracker credentials, .env and the NiceGUI user storage — hidden at runtime by
the data/ mount, but readable by anyone with the image.
"""

from fnmatch import fnmatchcase

import pytest

SECRETS = [
    "data/worktimer.db",
    "data/.pat_key",
    "data/.storage_secret",
    "data/notes/todo.md",
    "data/backups/worktimer_2026-01-01_000000.db",
    "backups/worktimer_2026-01-01_000000.db",
    ".env",
    ".nicegui/storage-general.json",
    ".git/config",
    "worktimer.db",
]

NEEDED_BY_THE_BUILD = [
    "main.py",
    "pyproject.toml",
    "uv.lock",
    "src/database.py",
    "config/config_ui.yml",
    "docs/CHANGELOG.md",
    "icons/worktimer.ico",
]


def _patterns(project_root) -> list[str]:
    lines = (project_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    return [ln.strip().rstrip("/") for ln in lines if ln.strip() and not ln.startswith("#")]


def _excluded(path: str, patterns: list[str]) -> bool:
    """Docker semantics without `**`: a pattern matches a path (or one of its
    parent directories) segment by segment — `*` never crosses a `/`."""
    parts = path.split("/")
    for n in range(1, len(parts) + 1):
        prefix = parts[:n]
        for pat in patterns:
            pat_parts = pat.split("/")
            if len(pat_parts) == len(prefix) and all(
                fnmatchcase(p, q) for p, q in zip(prefix, pat_parts)
            ):
                return True
    return False


def test_no_re_include_rules(project_root):
    assert not [p for p in _patterns(project_root) if p.startswith("!")]


@pytest.mark.parametrize("path", SECRETS)
def test_local_state_stays_out_of_the_image(project_root, path):
    assert _excluded(path, _patterns(project_root)), path


@pytest.mark.parametrize("path", NEEDED_BY_THE_BUILD)
def test_the_app_itself_is_still_copied(project_root, path):
    assert not _excluded(path, _patterns(project_root)), path
