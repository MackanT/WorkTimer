"""Tests for src/ui_styles.py — theme resolution, once per palette's content
(each viewer's own palette: tests/test_per_user_settings.py)."""

from src.ui_styles import UIStyles


def test_each_palette_is_resolved_once_by_content():
    first = UIStyles.resolved_for({"colors": {"muted": "slate-400", "accent": "sky-400"}})

    # Same content (another dict) -> the same resolved styles, not a new pass.
    assert UIStyles.resolved_for({"colors": {"muted": "slate-400", "accent": "sky-400"}}) is first
    # Changed content -> resolved anew.
    changed = UIStyles.resolved_for({"colors": {"muted": "red-400", "accent": "sky-400"}})
    assert changed is not first
    assert changed["layouts"]["muted_text"] == "text-red-400"


def test_a_palette_may_be_flat_or_nested():
    flat = UIStyles.resolved_for({"muted": "slate-500"})  # the flat colours dict

    assert UIStyles.resolved_for({"colors": {"muted": "slate-500"}}) is flat  # equivalent nested


def test_widget_width_falls_back_to_standard():
    styles = UIStyles.get_instance()
    standard = styles.get_widget_width("standard")
    assert isinstance(standard, str) and standard
    assert styles.get_widget_width("does-not-exist") == standard
