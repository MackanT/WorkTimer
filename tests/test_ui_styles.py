"""Tests for src/ui_styles.py — content-idempotent theme resolution (§8.10)."""

from src.ui_styles import UIStyles


def test_configure_theme_is_idempotent_by_content():
    UIStyles._theme_signature = None
    UIStyles.configure_theme({"colors": {"muted": "slate-400", "accent": "sky-400"}})
    sig1 = UIStyles._theme_signature
    assert sig1 is not None

    # Same content -> no re-resolution (signature unchanged).
    UIStyles.configure_theme({"colors": {"muted": "slate-400", "accent": "sky-400"}})
    assert UIStyles._theme_signature == sig1

    # Changed content -> re-resolves.
    UIStyles.configure_theme({"colors": {"muted": "red-400", "accent": "sky-400"}})
    assert UIStyles._theme_signature != sig1


def test_configure_theme_accepts_flat_or_nested():
    UIStyles._theme_signature = None
    UIStyles.configure_theme({"muted": "slate-400"})  # flat colours dict
    flat_sig = UIStyles._theme_signature
    UIStyles.configure_theme({"colors": {"muted": "slate-400"}})  # equivalent nested
    assert UIStyles._theme_signature == flat_sig


def test_widget_width_falls_back_to_standard():
    styles = UIStyles.get_instance()
    standard = styles.get_widget_width("standard")
    assert isinstance(standard, str) and standard
    assert styles.get_widget_width("does-not-exist") == standard
