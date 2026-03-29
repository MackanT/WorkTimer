"""
Dynamic UI Widgets

Self-refreshing widgets that know how to update their own data.
Base class handles parent-child relationships, data fetching, and common operations.
"""

from abc import ABC, abstractmethod
from nicegui import ui
from typing import Callable, Optional, Any, Dict
from datetime import date


class DynamicWidget(ABC):
    """
    Abstract base class for all dynamic widgets.

    Handles:
    - Parent-child relationships and auto-wiring
    - Data fetching and refresh logic
    - Value proxying to underlying widget
    - Common widget operations
    """

    def __init__(
        self,
        name: str,
        data_fetcher: Optional[Callable] = None,
        options_source: str = "",
        parent: Optional["DynamicWidget"] = None,
        label: str = "",
        initial_value: Any = None,
        field_config: Dict = None,
        **widget_kwargs,
    ):
        """
        Initialize dynamic widget.

        Args:
            name: Field name
            data_fetcher: Async callable(options_source, parent_val) -> data for refresh
            options_source: Key in data_sources dict to fetch data from
            parent: Parent DynamicWidget (for dependent fields)
            label: Widget label
            initial_value: Initial value to set
            field_config: Full field configuration dict
            **widget_kwargs: Additional args passed to widget creation
        """
        self.name = name
        self.data_fetcher = data_fetcher
        self.options_source = options_source
        self.parent = parent
        self.label = label
        self.field_config = field_config or {}
        self.widget_kwargs = widget_kwargs

        # Create the actual UI widget (implemented by subclass)
        self.widget = self._create_widget()

        # Set initial value if provided
        if initial_value is not None:
            self.widget.value = initial_value
        elif "default" in self.field_config:
            self.widget.value = self.field_config["default"]

        # Auto-wire to parent if exists
        if self.parent:
            # Check if parent_update is enabled (for HTML/markdown previews)
            if self.field_config.get("parent_update", False):
                # Wire up on_change for live updates
                if hasattr(self.parent.widget, "on_change"):
                    self.parent.widget.on_change(lambda e: self._on_parent_change())
                elif hasattr(self.parent.widget, "on_value_change"):
                    self.parent.widget.on_value_change(
                        lambda e: self._on_parent_change()
                    )
            else:
                # Standard parent-child relationship (value changes)
                if hasattr(self.parent.widget, "on_value_change"):
                    self.parent.widget.on_value_change(
                        lambda e: self._on_parent_change()
                    )

    @abstractmethod
    def _create_widget(self):
        """Create and return the actual NiceGUI widget. Implemented by subclasses."""
        pass

    def _on_parent_change(self):
        """Called when parent value changes"""
        import asyncio

        asyncio.create_task(self.refresh())

    async def refresh(self):
        """Refresh widget data based on current parent value (if any)"""
        if not self.data_fetcher:
            return

        try:
            parent_val = self.parent.widget.value if self.parent else None
            await self._refresh_impl(parent_val)
        except Exception as e:
            print(f"Error refreshing {self.name}: {e}")

    async def _refresh_impl(self, parent_val):
        """
        Implement refresh logic for this widget type.
        Override in subclasses if needed. Default does nothing.
        """
        pass

    @property
    def value(self):
        """Get current value"""
        return self.widget.value

    @value.setter
    def value(self, val):
        """Set current value"""
        self.widget.value = val

    def update(self):
        """Update the widget"""
        self.widget.update()

    def on_value_change(self, handler):
        """Register value change handler"""
        self.widget.on_value_change(handler)

    def classes(self, *args, **kwargs):
        """Apply CSS classes to widget"""
        return self.widget.classes(*args, **kwargs)

    def props(self, *args, **kwargs):
        """Apply Quasar props to widget"""
        return self.widget.props(*args, **kwargs)

    def style(self, *args, **kwargs):
        """Apply inline styles to widget"""
        return self.widget.style(*args, **kwargs)

    def __getattr__(self, name):
        """Proxy all other attributes to underlying widget"""
        return getattr(self.widget, name)


class DynamicDropDown(DynamicWidget):
    """Dropdown with auto-refreshing options"""

    def _create_widget(self):
        """Create ui.select widget"""
        with_input = self.field_config.get("with_input", True)
        allow_custom = self.field_config.get("allow_custom", True)
        initial_options = self.field_config.get("options", [])

        # If this dropdown has a parent, start with empty options
        if self.parent and not initial_options:
            initial_options = []

        widget = ui.select(
            options=initial_options,
            label=self.label,
            with_input=with_input,
            **self.widget_kwargs,
        ).props("outlined")

        # Apply custom value mode if enabled
        if with_input and allow_custom:
            widget.props('new-value-mode="add-unique"')

        return widget

    async def _refresh_impl(self, parent_val):
        """Refresh dropdown options"""
        # Get fresh options from data fetcher
        new_options = await self.data_fetcher(self.options_source, parent_val)
        old_value = self.widget.value

        # Guard: only set options if we got a list back
        if isinstance(new_options, list):
            self.widget.options = new_options
            if old_value and old_value not in self.widget.options:
                self.widget.value = None
        else:
            # It's a plain value, not an options list — just set the value
            self.widget.value = new_options

        self.widget.update()

    @property
    def options(self):
        """Get current options"""
        return self.widget.options

    @options.setter
    def options(self, opts):
        """Set options"""
        self.widget.options = opts


class DynamicInput(DynamicWidget):
    """Text input with auto-refresh from parent"""

    def _create_widget(self):
        """Create ui.input widget"""
        return ui.input(label=self.label, **self.widget_kwargs).props("outlined")

    async def _refresh_impl(self, parent_val):
        """Refresh input value based on parent"""
        if not parent_val:
            self.widget.value = ""
            return

        # Get fresh value from data fetcher
        new_value = await self.data_fetcher(self.options_source, parent_val)

        if isinstance(new_value, dict) and parent_val in new_value:
            self.widget.value = new_value[parent_val]
        elif isinstance(new_value, str):
            self.widget.value = new_value
        else:
            self.widget.value = ""

        self.widget.update()


class DynamicTextArea(DynamicWidget):
    """Multi-line text input"""

    def _create_widget(self):
        return ui.textarea(label=self.label, **self.widget_kwargs).props("outlined")

    async def _refresh_impl(self, parent_val):
        if not parent_val:
            self.widget.value = ""
            return
        new_value = await self.data_fetcher(self.options_source, parent_val)
        if isinstance(new_value, str):
            self.widget.value = new_value
        else:
            self.widget.value = ""
        self.widget.update()


class DynamicNumber(DynamicWidget):
    """Number input with auto-refresh from parent"""

    def _create_widget(self):
        """Create ui.number widget"""
        min_val = self.field_config.get("min")
        max_val = self.field_config.get("max")
        step = self.field_config.get("step", 1)

        widget = ui.number(
            label=self.label, min=min_val, max=max_val, step=step, **self.widget_kwargs
        ).props("outlined")

        return widget

    async def _refresh_impl(self, parent_val):
        """Refresh number value based on parent"""
        if not parent_val:
            self.widget.value = 0
            return

        # Get fresh value from data fetcher
        new_value = await self.data_fetcher(self.options_source, parent_val)

        if isinstance(new_value, dict) and parent_val in new_value:
            val = new_value[parent_val]
            self.widget.value = int(val) if val is not None else 0
        elif isinstance(new_value, (int, float)):
            self.widget.value = new_value
        else:
            self.widget.value = 0

        self.widget.update()


class DynamicDateInput(DynamicWidget):
    """Date input with picker (using ui.input with date menu)"""

    def _create_widget(self):
        """Create ui.input with date picker menu"""
        default_val = self.field_config.get("default", date.today().isoformat())

        # Create input with date picker
        date_input = ui.input(
            label=self.label, value=default_val, **self.widget_kwargs
        ).props("readonly outlined")

        # Add date picker menu
        with date_input:
            with ui.menu().props("no-parent-event") as menu:
                with ui.date().bind_value(date_input):
                    with ui.row().classes("justify-end"):
                        ui.button("Close", on_click=menu.close).props("flat")
            with date_input.add_slot("append"):
                ui.icon("edit_calendar").on("click", menu.open).classes(
                    "cursor-pointer"
                )

        return date_input

    async def _refresh_impl(self, parent_val):
        """Refresh date value based on parent"""
        if not parent_val:
            self.widget.value = date.today().isoformat()
            return

        # Get fresh value from data fetcher
        new_value = await self.data_fetcher(self.options_source, parent_val)

        if isinstance(new_value, dict) and parent_val in new_value:
            self.widget.value = new_value[parent_val]
        elif isinstance(new_value, str):
            self.widget.value = new_value
        else:
            self.widget.value = date.today().isoformat()

        self.widget.update()


class DynamicSwitch(DynamicWidget):
    """Switch/toggle with auto-refresh from parent"""

    def _create_widget(self):
        """Create ui.switch widget"""
        return ui.switch(text=self.label, **self.widget_kwargs)

    async def _refresh_impl(self, parent_val):
        """Refresh switch value based on parent"""
        if not parent_val:
            self.widget.value = False
            return

        # Get fresh value from data fetcher
        new_value = await self.data_fetcher(self.options_source, parent_val)

        if isinstance(new_value, dict) and parent_val in new_value:
            self.widget.value = bool(new_value[parent_val])
        elif isinstance(new_value, bool):
            self.widget.value = new_value
        else:
            self.widget.value = False

        self.widget.update()


class DynamicChipGroup(DynamicWidget):
    """Chip group for tags with auto-refresh options"""

    def _create_widget(self):
        """Create chip group for tags"""
        self._selected_tags = []
        # Normalize tags immediately to avoid serialization issues
        self._available_tags = self._normalize_tags(
            self.field_config.get("options", [])
        )

        # Create container (no label - just chips)
        self._chips_row = ui.row().classes("gap-1 flex-wrap w-full")

        # Render initial chips
        self._render_chips()

        return self._chips_row

    def _normalize_tags(self, tag_configs):
        """Convert DevOpsTagConfig objects to simple dicts to avoid serialization issues"""
        normalized = []
        for tag_config in tag_configs:
            if hasattr(tag_config, "name"):
                # It's a DevOpsTagConfig object - extract properties
                normalized.append(
                    {
                        "name": tag_config.name,
                        "color": getattr(tag_config, "color", "grey"),
                        "icon": getattr(tag_config, "icon", None),
                    }
                )
            elif isinstance(tag_config, dict):
                # Already a dict
                normalized.append(tag_config)
            else:
                # Plain string
                normalized.append(
                    {"name": str(tag_config), "color": "grey", "icon": None}
                )
        return normalized

    def _render_chips(self):
        """Render chip buttons with color and icon from config"""
        self._chips_row.clear()

        with self._chips_row:
            for tag_info in self._available_tags:
                tag_name = tag_info["name"]
                tag_color = tag_info.get("color", "grey")
                tag_icon = tag_info.get("icon")

                is_selected = tag_name in self._selected_tags

                # Use checkmark icon when selected, original icon otherwise
                display_icon = "check" if is_selected else tag_icon

                chip = ui.chip(
                    tag_name,
                    icon=display_icon,
                    on_click=lambda t=tag_name: self._toggle_tag(t),
                ).props("clickable")

                # Always use config color (not primary when selected)
                chip.style(
                    f"background: {tag_color} !important; color: white !important;"
                )
                chip.props("text-color=white")

    def _toggle_tag(self, tag):
        """Toggle tag selection"""
        if tag in self._selected_tags:
            self._selected_tags.remove(tag)
        else:
            self._selected_tags.append(tag)
        self._render_chips()

    async def _refresh_impl(self, parent_val):
        """Refresh available tags"""
        # Get fresh options from data fetcher
        new_options = await self.data_fetcher(self.options_source, parent_val)
        # Normalize immediately to avoid serialization issues
        self._available_tags = self._normalize_tags(new_options if new_options else [])
        self._render_chips()

    @property
    def value(self):
        """Get selected tags as comma-separated string"""
        return ", ".join(self._selected_tags)

    @value.setter
    def value(self, val):
        """Set selected tags from comma-separated string"""
        if isinstance(val, str):
            self._selected_tags = [t.strip() for t in val.split(",") if t.strip()]
        elif isinstance(val, list):
            self._selected_tags = val
        else:
            self._selected_tags = []

        if hasattr(self, "_chips_row"):
            self._render_chips()


class DynamicCodeMirror(DynamicWidget):
    """CodeMirror editor with auto-refresh and template support"""

    def _create_widget(self):
        """Create CodeMirror editor"""
        from datetime import date

        language = self.field_config.get("type_language", "markdown")
        templates = self.field_config.get("templates", {})
        default_val = self.field_config.get("default", "")

        # If templates exist, start with empty content (will be filled by template handling)
        if templates:
            default_val = ""

        # Replace template variables
        if default_val:
            default_val = default_val.replace("{today}", str(date.today()))

        editor = ui.codemirror(
            default_val,
            language=language,
            theme="dracula",
            line_wrapping=True,
        )

        # Store template info for later setup
        if templates:
            editor._template_info = {
                "templates": templates,
                "parent_fields": self.field_config.get("parent_fields", []),
            }
        return editor

    async def _refresh_impl(self, parent_val):
        """Refresh editor content based on parent"""
        if not parent_val:
            return

        new_value = await self.data_fetcher(self.options_source, parent_val)
        if isinstance(new_value, str):
            self.widget.value = new_value
            self.widget.update()


class DynamicHtml(DynamicWidget):
    """HTML preview widget with auto-refresh"""

    def _create_widget(self):
        """Create HTML preview widget"""
        default_val = self.field_config.get("default", "")

        # Get sizing from field config
        size_name = self.field_config.get("size", "standard")

        # Get HTML-specific styling from helpers
        try:
            from .. import helpers

            html_style = helpers.UI_STYLES.get_widget_style(
                "html_preview", "full" if size_name == "full" else "standard"
            )

            html_widget = ui.html(default_val, **self.widget_kwargs)

            # Apply classes and styles
            html_classes = html_style.get("base", "")
            if size_name == "full" and html_style.get("full_extra"):
                html_classes += f" {html_style['full_extra']}"

            if html_classes:
                html_widget.classes(html_classes)

            if html_style.get("style"):
                html_widget.style(html_style["style"])

            return html_widget
        except Exception:
            # Fallback if helpers not available
            return ui.html(default_val, **self.widget_kwargs)

    async def _refresh_impl(self, parent_val):
        """Refresh HTML content based on parent"""
        # Get parent value directly (for parent_update=True)
        if self.parent and hasattr(self.parent.widget, "value"):
            content = self.parent.widget.value or ""

            # Apply render function if specified
            render_fn_name = self.field_config.get("render_function")
            if render_fn_name:
                try:
                    from .. import helpers

                    if hasattr(helpers, render_fn_name):
                        render_fn = getattr(helpers, render_fn_name)
                        content = render_fn(content)
                except Exception as e:
                    print(f"Error rendering HTML: {e}")

            # Update content - set it directly on the widget
            self.widget.set_content(content)
            self.widget.update()


class DynamicEditorWithPreview(DynamicWidget):
    """Combined code editor and preview widget with auto-refresh"""

    def _create_widget(self):
        """Create editor with side-by-side preview"""
        from .. import helpers

        language = self.field_config.get("language", "markdown")
        templates = self.field_config.get("templates")
        default_val = self.field_config.get("default", "")

        if templates:
            default_val = ""

        if default_val:
            default_val = default_val.replace("{today}", str(date.today()))

        self._container = ui.row().classes("gap-4 w-full")

        with self._container:
            with ui.column().classes("flex-1"):
                self._editor = (
                    ui.codemirror(
                        default_val,
                        language=language,
                        theme="dracula",
                        line_wrapping=True,
                    )
                    .classes("w-full")
                    .style("height: 400px; max-height: 400px; overflow: auto;")
                )

                if templates:
                    self._editor._template_info = {
                        "templates": templates,
                        "parent_fields": self.field_config.get("parent_fields", []),
                    }

            with ui.column().classes("flex-1"):
                html_style = helpers.UI_STYLES.get_widget_style("html_preview", "full")
                self._preview = ui.html("")

                html_classes = html_style.get("base", "")
                if html_style.get("full_extra"):
                    html_classes += f" {html_style['full_extra']}"
                if html_classes:
                    self._preview.classes(html_classes)
                if html_style.get("style"):
                    self._preview.style(html_style["style"])

                def update_preview(e):
                    content = self._editor.value or ""
                    render_fn_name = self.field_config.get("render_function")
                    if render_fn_name and hasattr(helpers, render_fn_name):
                        try:
                            render_fn = getattr(helpers, render_fn_name)
                            content = render_fn(content)
                        except Exception as ex:
                            print(f"Error rendering: {ex}")
                    self._preview.set_content(content)

                self._editor.on_value_change(update_preview)

        return self._container

    async def _refresh_impl(self, parent_val):
        """Refresh editor content based on parent"""
        if not parent_val:
            return

        new_value = await self.data_fetcher(self.options_source, parent_val)
        if isinstance(new_value, str):
            self._editor.value = new_value
            self._editor.update()

    @property
    def value(self):
        """Get editor value"""
        return self._editor.value if hasattr(self, "_editor") else ""

    @value.setter
    def value(self, val):
        """Set editor value"""
        if hasattr(self, "_editor"):
            self._editor.value = val

    def on_value_change(self, handler):
        """Register value change handler on the editor"""
        if hasattr(self, "_editor"):
            self._editor.on_value_change(handler)

    @property
    def widget(self):
        """Return the editor widget for compatibility with template handling"""
        return self._editor if hasattr(self, "_editor") else self._container

    @widget.setter
    def widget(self, val):
        """Allow widget assignment during initialization"""
        self._container = val

    def on_value_change(self, handler):
        """Register value change handler on the editor"""
        if hasattr(self, "_editor"):
            self._editor.on_value_change(handler)

    @property
    def widget(self):
        """Return the editor widget for compatibility with template handling"""
        return self._editor if hasattr(self, "_editor") else self._container

    @widget.setter
    def widget(self, val):
        """Allow widget assignment during initialization"""
        self._container = val


class DynamicMarkdown(DynamicWidget):
    """Markdown preview widget with auto-refresh"""

    def _create_widget(self):
        """Create markdown preview widget"""
        default_val = self.field_config.get("default", "")
        return ui.markdown(default_val, **self.widget_kwargs)

    async def _refresh_impl(self, parent_val):
        """Refresh markdown content based on parent"""
        # Get parent value directly (for parent_update=True)
        if self.parent and hasattr(self.parent.widget, "value"):
            content = self.parent.widget.value or ""
            self.widget.content = content
            self.widget.update()


# Widget type registry - maps field types to widget classes
WIDGET_CLASSES = {
    "select": DynamicDropDown,
    "input": DynamicInput,
    "text": DynamicInput,  # Alias
    "textarea": DynamicTextArea,
    "number": DynamicNumber,
    "date": DynamicDateInput,
    "switch": DynamicSwitch,
    "chip_group": DynamicChipGroup,
    "codemirror": DynamicCodeMirror,
    "html": DynamicHtml,
    "markdown": DynamicMarkdown,
    "editor_with_preview": DynamicEditorWithPreview,
}
