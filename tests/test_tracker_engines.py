"""Tracker engines are per user (v6 Phase 6), and a re-init stops the engine
it replaces — before, every re-init left the old engine's hourly and nightly
syncs running beside the new one's."""

import logging

from src.core import app as core_app


class _Engine:
    def __init__(self):
        self.stopped = 0

    def stop_scheduled_updates(self):
        self.stopped += 1


def _core(user_key, engine):
    core = core_app.AppCore.__new__(core_app.AppCore)  # no NiceGUI client needed
    core.user_key, core.tracker_engine, core.logger = user_key, engine, logging.getLogger("t")
    core._tracker_initialized, core._tracker_no_customers, core._tracker_last_attempt = True, False, 0

    async def no_init():
        pass

    core.initialize_trackers = no_init
    return core


def test_each_user_has_their_own_engine(monkeypatch):
    ada, bob = _Engine(), _Engine()
    monkeypatch.setattr(core_app, "_tracker_engines", {2: ada, 3: bob})

    assert core_app.get_tracker_engine(2) is ada
    assert core_app.get_tracker_engine(3) is bob
    assert core_app.get_tracker_engine(4) is None
    core = _core(3, None)
    assert core._adopt_tracker_engine() and core.tracker_engine is bob


async def test_a_reinit_stops_the_old_engines_syncs_and_only_that_users(monkeypatch):
    ada, bob = _Engine(), _Engine()
    monkeypatch.setattr(core_app, "_tracker_engines", {2: ada, 3: bob})
    core = _core(2, ada)

    core.force_tracker_reinit()

    assert ada.stopped == 1 and bob.stopped == 0
    assert core_app._tracker_engines == {3: bob}
    assert core.tracker_engine is None and not core._tracker_initialized
