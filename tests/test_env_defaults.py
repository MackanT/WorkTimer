"""Settings from the environment work without a .env file (fixed in 5.1.2).

`docker compose` passes a variable that's missing from .env as an empty
string, and the app turned an empty DB_NAME into the path data/ — a server
error on every page."""

import os
import re
from pathlib import Path

import pytest

from src.config import ConfigLoader

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"

# ${VAR}, ${VAR:-default}, ${VAR:?error} and bare $VAR ($$ is an escaped $).
_REFERENCE = re.compile(r"\$\{([^}]*)\}|(?<!\$)\$([A-Za-z_]\w*)")


def _variables_without_a_default(compose_text):
    missing = []
    for match in _REFERENCE.finditer(compose_text):
        body = match.group(1)
        if body is None or not re.fullmatch(r"\w+:[-?].*", body):
            missing.append(match.group(0))
    return missing


def test_every_compose_variable_has_a_default():
    """`:-default`, or `:?message` to insist on a value — never a silent
    blank."""
    assert _variables_without_a_default(COMPOSE.read_text(encoding="utf-8")) == []


def test_the_compose_check_spots_a_variable_without_a_default():
    assert _variables_without_a_default(
        "- DB_NAME=${DB_NAME}\n- A=$A\n- B=${B:-x}\n- C=${C:?set C}\n- D=$$D\n"
    ) == ["${DB_NAME}", "$A"]


def _settings(monkeypatch, tmp_path, **env):
    monkeypatch.chdir(tmp_path)  # _load_settings creates data/ under the cwd
    for name in ("DB_NAME", "DEBUG_MODE"):
        if name in env:
            monkeypatch.setenv(name, env[name])
        else:
            monkeypatch.delenv(name, raising=False)
    loader = ConfigLoader()
    loader._load_settings()
    return loader.configs["settings"]


@pytest.mark.parametrize("env", [{}, {"DB_NAME": ""}], ids=["unset", "empty"])
def test_a_missing_db_name_opens_the_default_database(monkeypatch, tmp_path, env):
    settings = _settings(monkeypatch, tmp_path, **env)

    assert settings.db_path == os.path.join("data", "worktimer.db")


def test_a_db_name_is_used_when_set(monkeypatch, tmp_path):
    assert _settings(monkeypatch, tmp_path, DB_NAME="other.db").db_path == os.path.join(
        "data", "other.db")


@pytest.mark.parametrize("value, expected", [("", False), ("false", False), ("true", True),
                                             ("TRUE", True)])
def test_debug_mode(monkeypatch, tmp_path, value, expected):
    assert _settings(monkeypatch, tmp_path, DEBUG_MODE=value).debug_mode is expected
