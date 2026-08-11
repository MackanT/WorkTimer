"""
Centralized UI styling configuration.

Loads config/config_ui_styles.yml once per process and resolves ``${key}``
theme placeholders. Split out of helpers.py (which re-exports UI_STYLES for
backward compatibility).
"""

import os
import re

import yaml


class UIStyles:
    """Centralized UI styling configuration loaded from YAML."""

    _instance = None
    _styles = None
    _resolved = None  # styles with ${key} placeholders resolved against theme
    _theme_signature = None  # content hash of the last theme resolved against

    @classmethod
    def get_instance(cls):
        """Get singleton instance of UIStyles."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        """Load styles from config file."""
        if UIStyles._styles is None:
            config_path = os.path.join(
                os.path.dirname(__file__), "..", "config", "config_ui_styles.yml"
            )
            with open(config_path, "r") as f:
                UIStyles._styles = yaml.safe_load(f)
            UIStyles._resolved = UIStyles._styles  # default: unresolved fallback

    @classmethod
    def configure_theme(cls, theme: dict) -> None:
        """Resolve all ${key} placeholders in styles using the loaded theme.

        Replaces ``${key}`` in any YAML string value with ``theme[key]``.
        Idempotent by theme CONTENT: calling again with the same theme is a
        no-op, while a changed theme (e.g. after a settings reload) re-resolves
        — no external flag resets needed.

        Example: ``"text-${muted}"`` with ``theme = {"muted": "slate-400"}``
        becomes ``"text-slate-400"``.
        """
        # theme dict may be the full config_theme.yml (with "colors" key) or just the
        # colors sub-dict — handle both.
        flat_theme = theme.get("colors", theme) if isinstance(theme, dict) else {}

        signature = repr(sorted(flat_theme.items()))
        if signature == cls._theme_signature:
            return
        cls._theme_signature = signature

        def _resolve(value):
            if isinstance(value, str):
                return re.sub(
                    r"\$\{(\w+)\}",
                    lambda m: flat_theme.get(m.group(1), m.group(0)),
                    value,
                )
            if isinstance(value, dict):
                return {k: _resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_resolve(item) for item in value]
            return value

        cls._resolved = _resolve(cls._styles)

    @property
    def _active(self) -> dict:
        """Return resolved styles if theme was configured, else raw styles."""
        return UIStyles._resolved if UIStyles._resolved is not None else UIStyles._styles

    def get_widget_width(self, size_name: str) -> str:
        """Get widget width classes by size name.

        Args:
            size_name: Name from widget_widths config (e.g., 'standard', 'full')

        Returns:
            CSS classes string (e.g., 'w-64', 'w-full flex-1')
        """
        return self._active["widget_widths"].get(
            size_name, self._active["widget_widths"]["standard"]
        )

    def get_container_width(self, size_name: str) -> str:
        """Get container max-width value.

        Args:
            size_name: Name from container_widths config (e.g., 'md', 'xl')

        Returns:
            Width value for max-w-{value}xl (e.g., '4', '7')
        """
        return self._active["container_widths"].get(
            size_name, self._active["container_widths"]["md"]
        )

    def get_layout_classes(self, layout_name: str) -> str:
        """Get predefined layout classes.

        Args:
            layout_name: Name from layouts config (e.g., 'form_row', 'card')

        Returns:
            CSS classes string
        """
        return self._active["layouts"].get(layout_name, "")

    def get_widget_style(self, widget_type: str, mode: str = "standard") -> dict:
        """Get widget-specific styling.

        Args:
            widget_type: Type of widget (e.g., 'codemirror', 'html_preview')
            mode: Style mode ('standard' or 'full')

        Returns:
            Dict with 'classes' and 'style' keys
        """
        widget_config = self._active["widget_styles"].get(widget_type, {})

        # If config has 'classes' key directly, return it as-is (simple style config)
        if "classes" in widget_config:
            return {
                "classes": widget_config.get("classes", ""),
                "style": widget_config.get("style", ""),
            }

        # Otherwise use the mode-based config (complex style config)
        return {
            "classes": widget_config.get(mode, widget_config.get("base", "")),
            "style": widget_config.get("style", ""),
            "base": widget_config.get("base", ""),
            "full_extra": widget_config.get("full_extra", ""),
        }

    def get_default_size(self, widget_type: str) -> str:
        """Get default size name for a widget type.

        Args:
            widget_type: Type of widget (e.g., 'input', 'select', 'codemirror')

        Returns:
            Size name from widget_widths (e.g., 'standard', 'full')
        """
        return self._active["default_sizes"].get(widget_type, "standard")

    def is_wide_widget(self, widget_type: str) -> bool:
        """Check if widget type triggers wide layout mode.

        Args:
            widget_type: Type of widget

        Returns:
            True if widget should trigger wide layout
        """
        return widget_type in self._active["wide_widget_types"]

    def get_card_classes(
        self, container_size: str = "md", layout_type: str = "card"
    ) -> str:
        """Get complete card classes with container size.

        Args:
            container_size: Size name from container_widths (e.g., 'xs', 'md', 'xl')
            layout_type: Layout type from layouts (e.g., 'card', 'card_padded', 'card_spaced')

        Returns:
            Complete CSS classes string for card
        """
        max_width = self.get_container_width(container_size)
        layout_classes = self.get_layout_classes(layout_type)
        return f"{layout_classes} max-w-{max_width}xl"

    def get_inline_style(self, module: str, style_name: str) -> str:
        """Get inline CSS style for a specific module and component.

        Args:
            module: Module name (e.g., 'time_tracking')
            style_name: Style component name (e.g., 'customer_card', 'project_row')

        Returns:
            Inline CSS style string
        """
        return self._active.get("inline_styles", {}).get(module, {}).get(style_name, "")


# Global instance
UI_STYLES = UIStyles.get_instance()
