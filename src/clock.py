"""The app's one source of "now" for anything on the user's calendar.

Timer starts and stops, "today" defaults, date-range presets and stored
timestamps all read the time through here, so the move to UTC storage with
per-user local display (docs/v6_plan.md §4) is a change to this module and its
callers' intent — not a hunt through the codebase.

Both functions currently return exactly what the standard library does: the
server's local time, naive. Technical timing — cache ages, retry cooldowns,
unique filenames, the 2 AM sync scheduler — deliberately keeps using the
standard library directly, because in v6 "local" becomes the *user's*
timezone, which is the wrong clock for server housekeeping.

Call as ``clock.now_local()`` (module attribute), so tests can freeze time by
patching one name.
"""

from datetime import date, datetime


def now_local() -> datetime:
    """The current local date and time (naive, server clock)."""
    return datetime.now()


def today_local() -> date:
    """The current local date (server clock)."""
    return date.today()
