"""Shared pytest fixtures for the WorkTimer regression suite.

Run with:  uv run pytest
"""

import logging
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def null_logger() -> logging.Logger:
    """A quiet logger so Database/engine internals don't spam test output."""
    lg = logging.getLogger("worktimer.tests")
    lg.handlers = [logging.NullHandler()]
    lg.propagate = False
    return lg


@pytest.fixture
def db(tmp_path, null_logger):
    """A fresh, initialized Database on a temp-file SQLite DB.

    Closed in teardown so the file lock is released before pytest cleans tmp_path
    (Windows otherwise can't remove an open .db).
    """
    from src.database import Database

    database = Database(str(tmp_path / "test.db"), null_logger)
    database.initialize_db()
    yield database
    database.close()
