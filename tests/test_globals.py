"""Tests for src/globals.py — shared DB (§3.1) and scheduler math (§1.6)."""

import datetime

from src.globals import QueryEngine, _seconds_until_next


def test_query_engines_share_one_database(tmp_path, null_logger):
    path = str(tmp_path / "shared.db")
    qe1 = QueryEngine(path, null_logger)
    qe2 = QueryEngine(path, null_logger)
    assert qe1.db is qe2.db  # one connection per file, not per tab


def test_seconds_until_next_uses_today_when_not_passed():
    now = datetime.datetime(2026, 8, 3, 0, 30)
    # 00:30 -> today's 02:00 is 1h30m away, NOT ~25h.
    assert _seconds_until_next(2, now) == 5400


def test_seconds_until_next_rolls_to_tomorrow_when_passed():
    now = datetime.datetime(2026, 8, 3, 3, 0)
    # 03:00 -> next 02:00 is tomorrow, 23h away.
    assert _seconds_until_next(2, now) == 23 * 3600


def test_seconds_until_next_exactly_on_hour_rolls_forward():
    now = datetime.datetime(2026, 8, 3, 2, 0)
    assert _seconds_until_next(2, now) == 24 * 3600


def test_seconds_until_next_midnight():
    # Midnight = hour 0 — used by the time-tracker's midnight date-rollover timer.
    assert _seconds_until_next(0, datetime.datetime(2026, 8, 3, 14, 30)) == 9.5 * 3600
    assert _seconds_until_next(0, datetime.datetime(2026, 8, 3, 23, 59)) == 60
