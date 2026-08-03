"""Tests for src/core/events.py — register_unique prevents SPA handler leaks (§1.3)."""

from src.core.events import EventBus


def test_register_unique_replaces_same_key():
    bus = EventBus()
    bus.register_unique("evt", lambda **k: None, key="page")
    bus.register_unique("evt", lambda **k: None, key="page")
    # Same key -> the second replaces the first (no stacking across SPA re-visits).
    assert len(bus._handlers["evt"]) == 1


def test_register_unique_different_keys_stack():
    bus = EventBus()
    bus.register_unique("evt", lambda **k: None, key="a")
    bus.register_unique("evt", lambda **k: None, key="b")
    assert len(bus._handlers["evt"]) == 2


def test_register_and_unregister():
    bus = EventBus()
    handler = bus.register("evt", lambda **k: None)
    assert len(bus._handlers["evt"]) == 1
    bus.unregister("evt", handler)
    assert len(bus._handlers["evt"]) == 0


def test_unregister_missing_handler_is_safe():
    bus = EventBus()
    bus.unregister("evt", lambda **k: None)  # should not raise
