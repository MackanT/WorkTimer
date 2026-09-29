"""Tracker syncs across users (v6 Phase 6, slice 4): at most SYNC_SLOTS run at
once, and each user's schedule has its own fixed offset — hourly syncs spread
over the hour, nightly full refreshes over 02:00–04:00."""

import asyncio
import datetime
import logging
import weakref
from types import SimpleNamespace

import pytest

from src import globals as wt_globals
from src.globals import NIGHTLY_SPREAD, TrackerEngine, _seconds_until_offset, _stagger


def _engine(user_key):
    engine = TrackerEngine(query_engine=SimpleNamespace(user_key=user_key),
                           log_engine=logging.getLogger("sync-test"))
    engine.manager = object()  # "connected"
    return engine


def test_ten_users_hourly_syncs_spread_over_the_hour():
    offsets = sorted(_stagger(key, 3600) for key in range(1, 11))

    assert all(0 <= o < 3600 for o in offsets)
    assert min(b - a for a, b in zip(offsets, offsets[1:])) >= 3 * 60


def test_a_users_hourly_sync_is_at_their_own_minute():
    hour = 5 * 3600
    assert _seconds_until_offset(600, 3600, now=hour + 100) == 500
    assert _seconds_until_offset(600, 3600, now=hour + 600) == 3600  # just ran: next hour
    ada, bob = _engine(2), _engine(3)
    assert 0 < ada.next_hourly_wait(hour) <= 3600
    assert ada.next_hourly_wait(hour) != bob.next_hourly_wait(hour)


def test_the_nightly_refresh_is_between_2_and_4_and_today_if_still_ahead():
    engine = _engine(2)
    slot = datetime.datetime(2026, 9, 29, 2) + datetime.timedelta(
        seconds=_stagger(2, NIGHTLY_SPREAD))

    one_am = engine.next_nightly_wait(datetime.datetime(2026, 9, 29, 1))
    assert 3600 <= one_am < 3600 + NIGHTLY_SPREAD
    assert engine.next_nightly_wait(slot - datetime.timedelta(minutes=1)) == pytest.approx(60)
    assert engine.next_nightly_wait(slot + datetime.timedelta(minutes=1)) == pytest.approx(86400 - 60)


@pytest.fixture
def slots(monkeypatch):
    monkeypatch.setattr(wt_globals, "SYNC_SLOTS", 2)
    monkeypatch.setattr(wt_globals, "_sync_slots", weakref.WeakKeyDictionary())


def _counting(monkeypatch):
    seen = {"running": 0, "peak": 0}

    async def fake_sync(self, incremental):
        seen["running"] += 1
        seen["peak"] = max(seen["peak"], seen["running"])
        await asyncio.sleep(0.02)
        seen["running"] -= 1

    monkeypatch.setattr(TrackerEngine, "_update_devops_locked", fake_sync)
    return seen


async def test_users_syncs_share_the_cap(slots, monkeypatch):
    seen = _counting(monkeypatch)

    await asyncio.gather(*(_engine(key).refresh_tracker_data() for key in range(2, 7)))

    assert seen["peak"] == 2


async def test_one_users_syncs_still_run_one_at_a_time(slots, monkeypatch):
    seen = _counting(monkeypatch)
    engine = _engine(2)

    await asyncio.gather(engine.refresh_tracker_data(), engine.refresh_tracker_data(incremental=True))

    assert seen["peak"] == 1
