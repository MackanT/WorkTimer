"""Each user's own files and logs (v6 Phase 6, slice 2): user 1 keeps data/,
everyone else gets data/users/<key>/; a user's Log page shows only their own
lines."""

import logging
from collections import deque

import pytest

from _access import CONFIG
from src import auth
from src.auth import AuthConfig
from src.core import app as core_app
from src.core import events
from src.pages import notepad
from src.user_paths import user_dir


def test_user_1_keeps_data_and_everyone_else_gets_their_own(tmp_path):
    assert user_dir(tmp_path, 1) == tmp_path
    assert user_dir(tmp_path, 2) == tmp_path / "users" / "2"
    for bad in (0, -1, None, "2", True):
        with pytest.raises(ValueError):
            user_dir(tmp_path, bad)


def test_notes_are_per_user(tmp_path, monkeypatch):
    monkeypatch.setattr(notepad, "DATA_DIR", tmp_path)

    assert notepad.get_notes_dir() == tmp_path / "notes"
    assert notepad.get_notes_dir(2) == tmp_path / "users" / "2" / "notes"
    assert notepad.get_notes_dir(2).is_dir()


class _Bus:
    def __init__(self):
        self._recent_logs = deque()
        self.seen = []

    def emit(self, event, **item):
        self.seen.append(item["message"])


def _core(user_key):
    core = core_app.AppCore.__new__(core_app.AppCore)  # no NiceGUI client needed
    core.user_key, core.event_bus, core.debug = user_key, _Bus(), False
    core._log_handlers, core._root_logger_attached = [], False
    return core


def test_each_users_log_page_gets_only_their_own_lines(monkeypatch):
    monkeypatch.setattr(events, "_RECENT_LOGS", {})
    ada, bob, ada_tab2 = _core(2), _core(3), _core(2)
    try:
        ada_log, bob_log = ada._setup_logger("Database"), bob._setup_logger("Database")
        ada_tab2._setup_logger("Database")
        ada_log.info("Acme saved")
        bob_log.info("Beta saved")

        assert ada.event_bus.seen == ada_tab2.event_bus.seen == ["Acme saved"]
        assert bob.event_bus.seen == ["Beta saved"]
        assert {i["message"] for i in events.get_recent_logs(2)} == {"Acme saved"}
        assert events.get_recent_logs(2)[0]["logger"] == "Database"
        assert [i["message"] for i in events.get_recent_logs(3)] == ["Beta saved"]
    finally:
        for core in (ada, bob, ada_tab2):
            core.detach_log_handlers()


@pytest.mark.parametrize("config, listens", [(AuthConfig(), True), (CONFIG, False)])
def test_only_a_single_user_tab_listens_to_the_root_logger(monkeypatch, config, listens):
    """The root logger carries every library's and every user's records."""
    monkeypatch.setattr(auth, "_config", config)
    root = logging.getLogger()
    level = root.level
    core = _core(2)
    try:
        core._attach_root_logger_handler()
        attached = any(isinstance(h, events.EventBusLogHandler) and h.event_bus is core.event_bus
                       for h in root.handlers)
        assert attached is listens
    finally:
        core.detach_log_handlers()
        root.setLevel(level)
