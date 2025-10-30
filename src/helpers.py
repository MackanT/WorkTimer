import os
import asyncio
import yaml
from nicegui import ui
from datetime import date, timedelta
import re
import numpy as np
import markdown as _markdown
import bleach as _bleach
from markdownify import markdownify as _markdownify

from .globals import SaveData


# ===== UI STYLE MANAGER =====
class UIStyles:
    """Centralized UI styling configuration loaded from YAML."""

    _instance = None
    _styles = None

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

    def get_widget_width(self, size_name: str) -> str:
        """Get widget width classes by size name.

        Args:
            size_name: Name from widget_widths config (e.g., 'standard', 'full')

        Returns:
            CSS classes string (e.g., 'w-64', 'w-full flex-1')
        """
        return self._styles["widget_widths"].get(
            size_name, self._styles["widget_widths"]["standard"]
        )

    def get_container_width(self, size_name: str) -> str:
        """Get container max-width value.

        Args:
            size_name: Name from container_widths config (e.g., 'md', 'xl')

        Returns:
            Width value for max-w-{value}xl (e.g., '4', '7')
        """
        return self._styles["container_widths"].get(
            size_name, self._styles["container_widths"]["md"]
        )

    def get_layout_classes(self, layout_name: str) -> str:
        """Get predefined layout classes.

        Args:
            layout_name: Name from layouts config (e.g., 'form_row', 'card')

        Returns:
            CSS classes string
        """
        return self._styles["layouts"].get(layout_name, "")

    def get_widget_style(self, widget_type: str, mode: str = "standard") -> dict:
        """Get widget-specific styling.

        Args:
            widget_type: Type of widget (e.g., 'codemirror', 'html_preview')
            mode: Style mode ('standard' or 'full')

        Returns:
            Dict with 'classes' and 'style' keys
        """
        widget_config = self._styles["widget_styles"].get(widget_type, {})
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
        return self._styles["default_sizes"].get(widget_type, "standard")

    def is_wide_widget(self, widget_type: str) -> bool:
        """Check if widget type triggers wide layout mode.

        Args:
            widget_type: Type of widget

        Returns:
            True if widget should trigger wide layout
        """
        return widget_type in self._styles["wide_widget_types"]

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


# Global instance
UI_STYLES = UIStyles.get_instance()


# ===== MARKDOWN & HTML RENDERING =====


def render_and_sanitize_markdown(text: str) -> str:
    """Convert markdown to sanitized HTML with dark mode styling.

    Args:
        text: Markdown text to render

    Returns:
        Sanitized HTML string with inline CSS for dark mode
    """
    if not text:
        return "<p style='color: #999;'>No content to preview</p>"

    # Render markdown with proper extensions
    raw_html = _markdown.markdown(
        text,
        extensions=[
            "fenced_code",
            "codehilite",
            "tables",
            "nl2br",  # Convert newlines to <br>
            "sane_lists",  # Better list handling
        ],
    )

    allowed_tags = list(_bleach.sanitizer.ALLOWED_TAGS) + [
        "p",
        "pre",
        "code",
        "span",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "img",
        "br",
        "hr",
        "ul",
        "ol",
        "li",
        "blockquote",
        "strong",
        "em",
        "del",
        "ins",
    ]
    allowed_attrs = {
        "a": ["href", "title", "target"],
        "img": ["src", "alt", "width", "height"],
        "code": ["class"],
        "pre": ["class"],
        "span": ["class"],
        "*": ["class"],
    }

    cleaned_html = _bleach.clean(
        raw_html,
        tags=allowed_tags,
        attributes=allowed_attrs,
        protocols=["http", "https", "mailto"],
    )

    # Add comprehensive styling for markdown elements (dark mode)
    return f"""
    <div style="font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #e0e0e0;">
        <style>
            h1 {{ font-size: 2em; font-weight: bold; margin: 0.67em 0; border-bottom: 2px solid #555; padding-bottom: 0.3em; color: #ffffff; }}
            h2 {{ font-size: 1.5em; font-weight: bold; margin: 0.75em 0; border-bottom: 1px solid #555; padding-bottom: 0.3em; color: #f0f0f0; }}
            h3 {{ font-size: 1.25em; font-weight: bold; margin: 0.83em 0; color: #f0f0f0; }}
            h4 {{ font-size: 1.1em; font-weight: bold; margin: 1em 0; color: #e8e8e8; }}
            h5 {{ font-size: 1em; font-weight: bold; margin: 1.17em 0; color: #e8e8e8; }}
            h6 {{ font-size: 0.9em; font-weight: bold; margin: 1.33em 0; color: #aaa; }}
            ul, ol {{ margin: 1em 0; padding-left: 2em; color: #e0e0e0; }}
            ul {{ list-style-type: disc; }}
            ol {{ list-style-type: decimal; }}
            li {{ margin: 0.25em 0; }}
            p {{ margin: 1em 0; color: #e0e0e0; }}
            blockquote {{ 
                border-left: 4px solid #666; 
                padding-left: 1em; 
                margin: 1em 0;
                color: #aaa;
                font-style: italic;
            }}
            code {{ 
                background-color: #2d2d2d; 
                color: #f8f8f2;
                padding: 2px 6px; 
                border-radius: 3px;
                font-family: 'Courier New', monospace;
                font-size: 0.9em;
            }}
            pre {{ 
                background-color: #2d2d2d; 
                padding: 16px; 
                border-radius: 6px; 
                overflow-x: auto;
                border: 1px solid #444;
            }}
            pre code {{
                background-color: transparent;
                padding: 0;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 1em 0;
            }}
            th, td {{
                border: 1px solid #555;
                padding: 8px;
                text-align: left;
                color: #e0e0e0;
            }}
            th {{
                background-color: #2d2d2d;
                font-weight: bold;
            }}
            strong {{ font-weight: bold; color: #ffffff; }}
            em {{ font-style: italic; }}
            hr {{ 
                border: none; 
                border-top: 2px solid #555; 
                margin: 2em 0; 
            }}
            a {{
                color: #64b5f6;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
        </style>
        {cleaned_html}
    </div>
    """


def convert_html_to_markdown(html_text: str) -> str:
    """Convert HTML content to clean markdown text.

    Args:
        html_text: HTML content to convert

    Returns:
        Clean markdown text suitable for editing
    """
    if not html_text or not html_text.strip():
        return ""

    # Pre-process to remove script and style tags
    import re

    html_text = re.sub(
        r"<script[^>]*>.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE
    )
    html_text = re.sub(
        r"<style[^>]*>.*?</style>", "", html_text, flags=re.DOTALL | re.IGNORECASE
    )

    # Use markdownify to convert HTML to markdown
    markdown_text = _markdownify(
        html_text,
        heading_style="atx",  # Use # style headers
        bullets="-",  # Use - for bullet points
        autolinks=False,  # Don't auto-convert URLs
        default_title=True,  # Include title attributes
    ).strip()

    # Clean up common HTML artifacts that might remain
    import html

    markdown_text = html.unescape(markdown_text)

    # Clean up excessive whitespace and normalize line breaks
    lines = markdown_text.split("\n")
    cleaned_lines = []

    for line in lines:
        line = line.rstrip()  # Remove trailing whitespace
        cleaned_lines.append(line)

    # Join lines and remove excessive blank lines
    result = "\n".join(cleaned_lines)

    # Replace multiple consecutive blank lines with just two
    result = re.sub(r"\n\n\n+", "\n\n", result)

    return result.strip()


# ===== DATE & TIME UTILITIES =====


def get_range_for(option: str) -> str:
    """Get date range string for a given time period option.

    Args:
        option: Time period option ("Day", "Week", "Month", "Year", "All-Time")

    Returns:
        Formatted date range string "start - end"
    """
    today = date.today()

    if option == "Day":
        return f"{today} - {today}"

    if option == "Week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return f"{start} - {end}"

    if option == "Month":
        start = today.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
        return f"{start} - {end}"

    if option == "Year":
        start = today.replace(month=1, day=1)
        end = today.replace(month=12, day=31)
        return f"{start} - {end}"

    if option == "All-Time":
        # TODO: Get min(start_date) from database instead of hardcoded value
        start = date(2000, 1, 1)
        end = today
        return f"{start} - {end}"

    return ""


def parse_date_range(date_range_str: str) -> tuple[str | None, str | None]:
    """Parse date range string into start and end dates.

    Args:
        date_range_str: Date range in format 'YYYYMMDD - YYYYMMDD' or 'YYYY-MM-DD - YYYY-MM-DD'

    Returns:
        Tuple of (start_date, end_date) as strings without dashes, or (None, None) if invalid
    """
    if not date_range_str:
        return None, None

    match = re.match(
        r"(\d{4}-?\d{2}-?\d{2})\s*-\s*(\d{4}-?\d{2}-?\d{2})", date_range_str
    )
    if match:
        start, end = match.groups()
        # Remove dashes if present
        start = start.replace("-", "")
        end = end.replace("-", "")
        return start, end

    return None, None


# ===== INPUT VALIDATION & FEEDBACK =====


def check_input(widgets: dict, required_fields: list[str]) -> bool:
    """Validate that required fields have values.

    Args:
        widgets: Dictionary of widget instances
        required_fields: List of field names that must have values

    Returns:
        True if all required fields have values, False otherwise
    """
    is_ok = True
    for field in required_fields:
        widget = widgets.get(field)
        if widget is None:
            continue  # Skip missing widgets

        # Get widget value safely - some widgets don't have .value attribute
        widget_value = None
        if hasattr(widget, "value"):
            widget_value = widget.value
        elif isinstance(widget, list) and widget and hasattr(widget[0], "selected"):
            # Handle chip groups - check if any chips are selected
            widget_value = any(getattr(chip, "selected", False) for chip in widget)

        # Check if the widget has a value
        if not widget_value:
            ui.notify(
                f"{field.replace('_', ' ').title()} is required!",
                color="negative",
            )
            is_ok = False
    return is_ok


def print_success(
    table: str, main_param: str, action_type: str, widgets: dict = None
) -> tuple[str, str]:
    """Display success notification and generate log messages.

    Args:
        table: Table/entity name
        main_param: Main parameter name (e.g., 'customer_name')
        action_type: Action performed (e.g., 'added', 'updated')
        widgets: Optional dict of widget instances to log parameter values

    Returns:
        Tuple of (notification_message, log_message)
    """
    msg_1 = f"{table} {main_param} {action_type}!"
    ui.notify(msg_1, color="positive")

    if widgets:
        print_msg = "Parameters: "
        for field in widgets:
            print_msg += f"{field}: {widgets[field].value}, "
        print_msg = print_msg.rstrip(", ")
        return msg_1, print_msg

    return msg_1, "No data to display."


# ===== TEXT PARSING UTILITIES =====


def extract_table_name(query_text: str) -> str:
    match = re.search(r"from\s+([^\s;]+)", query_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "unknown_table"


def extract_devops_id(text: str) -> int | None:
    """Extract DevOps ID from text containing pattern ': ID -'.

    Args:
        text: Text to search for DevOps ID

    Returns:
        Extracted ID as integer, or None if not found
    """
    match = re.search(r":\s*(\d+)\s*-", text)
    if match:
        return int(match.group(1))
    return None


# ===== UI WIDGET FACTORIES =====


def date_input(label, input_width: str = "w-64"):
    with ui.input(label).props("readonly").classes(input_width) as date:
        with ui.menu().props("no-parent-event") as menu:
            with ui.date().bind_value(date):
                with ui.row().classes("justify-end"):
                    ui.button("Close", on_click=menu.close).props("flat")
        with date.add_slot("append"):
            ui.icon("edit_calendar").on("click", menu.open).classes("cursor-pointer")
    return date


def setup_template_handling(widgets: dict):
    """Set up template handling for codemirror widgets with templates."""
    from datetime import date

    # Find codemirror widgets with template info
    template_widgets = {}
    for widget_name, widget in widgets.items():
        if hasattr(widget, "_template_info"):
            template_widgets[widget_name] = widget

    if not template_widgets:
        return

    # Set up template selection based on work_item_type
    work_item_type_widget = widgets.get("work_item_type")
    if not work_item_type_widget:
        return

    def update_templates(e=None, parent_field_changed=None):
        current_type = (
            work_item_type_widget.value if work_item_type_widget.value else "User Story"
        )

        for widget_name, widget in template_widgets.items():
            template_info = widget._template_info
            templates = template_info["templates"]
            parent_fields = template_info["parent_fields"]

            if parent_field_changed:
                # Only update specific parent field placeholder, don't reload entire template
                current_content = widget.value or ""
                parent_widget = widgets.get(parent_field_changed)

                if parent_widget and parent_field_changed in parent_fields:
                    # Update specific lines that contain the field placeholder
                    lines = current_content.split("\n")
                    updated_lines = []

                    for line in lines:
                        # Look for lines that mention the field (e.g., "**Source:**" or "**Contact:**")
                        if parent_field_changed == "source" and "**Source:**" in line:
                            updated_lines.append(
                                f"**Source:** {parent_widget.value or ''}"
                            )
                        elif (
                            parent_field_changed == "contact_person"
                            and "**Contact:**" in line
                        ):
                            updated_lines.append(
                                f"**Contact:** {parent_widget.value or ''}"
                            )
                        else:
                            updated_lines.append(line)

                    widget.value = "\n".join(updated_lines)
            else:
                # Full template reload (only when work_item_type changes)
                template_content = templates.get(current_type, "")

                if template_content:
                    # Replace {today} placeholder
                    content = template_content.replace("{today}", str(date.today()))

                    # Replace parent field placeholders if they exist
                    for parent_field in parent_fields:
                        parent_widget = widgets.get(parent_field)
                        if parent_widget and parent_widget.value:
                            placeholder = "{" + parent_field + "}"
                            content = content.replace(
                                placeholder, str(parent_widget.value)
                            )

                    # Update the editor content
                    widget.value = content

    # Bind to work_item_type changes (full template reload)
    work_item_type_widget.on_value_change(lambda e: update_templates(e, None))

    # Also bind to parent field changes for surgical updates
    for widget_name, widget in template_widgets.items():
        template_info = widget._template_info
        parent_fields = template_info["parent_fields"]

        for parent_field in parent_fields:
            parent_widget = widgets.get(parent_field)
            if parent_widget:
                # Create a closure to capture the parent_field value
                def make_parent_handler(field_name):
                    return lambda e: update_templates(e, field_name)

                parent_widget.on_value_change(make_parent_handler(parent_field))

    # Set initial template
    update_templates()


def setup_conditional_visibility(widgets: dict, conditional_widgets: dict):
    """Set up conditional visibility for widgets based on other widget values."""

    def make_visibility_handler(conditional_widget_info):
        """Create a visibility handler for a conditional widget."""

        def handle_visibility(e=None):
            widget = conditional_widget_info["widget"]
            visible_when = conditional_widget_info["visible_when"]

            # Check all conditions
            is_visible = True
            for condition_field, condition_values in visible_when.items():
                condition_widget = widgets.get(condition_field)
                if condition_widget and condition_widget.value:
                    current_value = condition_widget.value
                    if isinstance(condition_values, list):
                        if current_value not in condition_values:
                            is_visible = False
                            break
                    else:
                        if current_value != condition_values:
                            is_visible = False
                            break
                else:
                    # If condition widget has no value, hide this widget
                    is_visible = False
                    break

            # Set visibility
            if is_visible:
                widget.set_visibility(True)
            else:
                widget.set_visibility(False)

        return handle_visibility

    # Set up handlers for each conditional widget
    for widget_name, widget_info in conditional_widgets.items():
        handler = make_visibility_handler(widget_info)
        visible_when = widget_info["visible_when"]

        # Bind the handler to all condition fields
        for condition_field in visible_when.keys():
            condition_widget = widgets.get(condition_field)
            if condition_widget:
                condition_widget.on_value_change(handler)

        # Call handler initially to set initial visibility
        handler()


def make_input_row(
    fields,
    layout_mode: str = None,
    widgets: dict = None,
    defer_parent_wiring: bool = False,
    render_functions: dict = None,
):
    """Create UI widgets for a list of field configs.

    Args:
        fields: List of field configuration dicts
        layout_mode: Optional layout mode override ("full" for wide layout, None for default per-widget sizing)
        widgets: Optional dict to update with created widgets
        defer_parent_wiring: If True, returns pending relations instead of binding immediately
        render_functions: Optional dict of render functions for html type fields

    Returns:
        If defer_parent_wiring: tuple (created_widgets, pending_relations)
        Otherwise: created_widgets dict
    """
    created = {}
    pending_relations = []
    conditional_widgets = {}  # Track widgets with conditional visibility

    for field in fields:
        label = field["label"]
        if field.get("optional", True):
            label += " (optional)"

        ftype = field["type"]
        fname = field["name"]

        # Determine widget width using UI_STYLES
        if layout_mode:
            # Layout mode specified (e.g., "full" for wide layouts)
            size_name = layout_mode
        else:
            # Use default size for this widget type
            size_name = UI_STYLES.get_default_size(ftype)

        widget_classes = UI_STYLES.get_widget_width(size_name)

        default_val = field.get("default")
        options_val = field.get("options")
        # Use options for default if present and not None
        if options_val is not None:
            if isinstance(options_val, list) and options_val:
                default_val = options_val[0]
            elif isinstance(options_val, (str, int, float)):
                default_val = options_val

        if ftype == "input":
            created[fname] = ui.input(label).classes(widget_classes)
            if default_val is not None:
                created[fname].value = default_val
        elif ftype == "text":
            created[fname] = ui.textarea(label).classes(widget_classes)
            if default_val is not None:
                created[fname].value = default_val
        elif ftype == "number":
            created[fname] = ui.number(label, min=0).classes(widget_classes)
            if default_val is not None:
                created[fname].value = default_val
        elif ftype == "date":
            created[fname] = date_input(label, input_width=widget_classes)
            if default_val is not None:
                created[fname].value = default_val
        elif ftype == "datetime":
            created[fname] = ui.input(label, placeholder="YYYY-MM-DD HH:MM:SS").classes(
                widget_classes
            )
            if default_val is not None:
                created[fname].value = default_val
        elif ftype == "select":
            if "parent" in field:
                options = []
            else:
                options = field.get("options", {})
            if options is None:
                options = []
            # Check if with_input is specified in field config, default to True
            with_input = field.get("with_input", True)
            select_widget = ui.select(options, label=label, with_input=with_input)
            # If with_input is enabled, allow adding new values
            if with_input:
                select_widget.props('new-value-mode="add-unique"')
            select_widget.classes(widget_classes)
            if "default" in field:
                select_widget.value = field["default"]
            created[fname] = select_widget
        elif ftype == "switch":
            created[fname] = ui.switch(text=label).classes(widget_classes)
            if "default" in field:
                created[fname].value = field["default"]
        elif ftype == "chip_group":
            chips = []
            # Get chip group specific styling
            chip_style = UI_STYLES.get_widget_style("chip_group")
            chip_row_class = f"{chip_style['base']} {widget_classes}"

            with ui.row().classes(chip_row_class):
                for tag in field["options"]:
                    chips.append(
                        ui.chip(
                            tag.name,
                            selectable=True,
                            icon=tag.icon,
                            color=tag.color,
                        )
                    )
            created[fname] = chips
        elif ftype == "codemirror":
            # Handle templates for codemirror based on work_item_type
            templates = field.get("templates", {})
            initial_content = default_val or ""

            # If templates are defined, we'll set up template selection
            # For now, start with empty content and set up template handling
            if templates:
                initial_content = ""

            # Replace template variables in content
            if initial_content:
                initial_content = initial_content.replace("{today}", str(date.today()))

            editor = ui.codemirror(
                initial_content,
                language=field.get("type_language", "markdown"),
                theme="dracula",
                line_wrapping=True,
            )

            # Get codemirror-specific styling
            code_style = UI_STYLES.get_widget_style(
                "codemirror", "full" if size_name == "full" else "standard"
            )
            editor.classes(f"{widget_classes} {code_style['classes']}")
            if code_style["style"]:
                editor.style(code_style["style"])
            created[fname] = editor

            # Store template info for later setup
            if templates:
                created[fname]._template_info = {
                    "templates": templates,
                    "parent_fields": field.get("parent_fields", []),
                }
        elif ftype == "markdown":
            # Markdown preview
            preview = ui.markdown(default_val or "").classes(widget_classes)
            created[fname] = preview
            created[f"{fname}_preview"] = preview
        elif ftype == "html":
            # HTML preview widget with dark mode styling
            html_style = UI_STYLES.get_widget_style(
                "html_preview", "full" if size_name == "full" else "standard"
            )

            # Build classes: widget width + base styling + any mode-specific extras
            html_classes = f"{widget_classes} {html_style['base']}"
            if size_name == "full" and html_style["full_extra"]:
                html_classes += f" {html_style['full_extra']}"

            html_widget = ui.html(default_val or "").classes(html_classes)
            if html_style["style"]:
                html_widget.style(html_style["style"])
            created[fname] = html_widget

        # Collect parent relationships for later binding
        if "parent" in field:
            pending_relations.append(
                {"child": fname, "parent": field["parent"], "field_config": field}
            )

        # Track conditional widgets
        if field.get("conditional") and field.get("visible_when"):
            conditional_widgets[fname] = {
                "widget": created[fname],
                "visible_when": field["visible_when"],
                "field_config": field,
            }

    # Merge created into provided widgets (if any)
    out_widgets = widgets if widgets is not None else {}
    # If widgets was None, ensure it's a new dict
    if widgets is None:
        out_widgets = created
    else:
        out_widgets.update(created)

    # Set up conditional field visibility
    if conditional_widgets:
        setup_conditional_visibility(out_widgets, conditional_widgets)

    # Set up template handling for codemirror widgets
    setup_template_handling(out_widgets)

    if defer_parent_wiring:
        return out_widgets, pending_relations

    # Otherwise bind relations immediately (backwards compatible behavior)
    bind_parent_relations(out_widgets, pending_relations, render_functions)
    return out_widgets


# ===== PARENT-CHILD WIDGET BINDING =====


def bind_parent_relations(
    widgets: dict,
    pending_relations: list,
    render_functions: dict = None,
    data_sources: dict = None,
):
    """Bind parent->child update handlers for pending relations.

    `pending_relations` is a list of dicts with keys: child, parent, field_config
    `render_functions` is an optional dict of render functions for html type fields
    `data_sources` is an optional dict of data sources for looking up default values
    """
    render_functions = render_functions or {}
    data_sources = data_sources or {}

    # Special handling for parent_name field that depends on both customer_name and work_item_type
    parent_name_widget = widgets.get("parent_name")
    customer_widget = widgets.get("customer_name")
    work_item_type_widget = widgets.get("work_item_type")

    if (
        parent_name_widget
        and customer_widget
        and work_item_type_widget
        and "parent_names" in data_sources
    ):

        def update_parent_name_options(e=None):
            customer = customer_widget.value
            work_item_type = work_item_type_widget.value
            parent_names_data = data_sources["parent_names"]

            if customer and work_item_type and isinstance(parent_names_data, dict):
                customer_data = parent_names_data.get(customer, {})
                if isinstance(customer_data, dict):
                    parent_name_widget.options = customer_data.get(work_item_type, [])
                else:
                    parent_name_widget.options = []
            else:
                parent_name_widget.options = []
            parent_name_widget.update()

        # Bind to both customer_name and work_item_type changes
        customer_widget.on_value_change(update_parent_name_options)
        work_item_type_widget.on_value_change(update_parent_name_options)

        # Set initial options
        update_parent_name_options()

    for rel in pending_relations:
        child = rel["child"]
        parent = rel["parent"]
        field_config = rel.get("field_config", {})

        def make_update_child(child=child, parent=parent, field_config=field_config):
            async def update_child(e):
                ftype = field_config.get("type")

                # Small delay to allow parent widget value to be updated (especially for CodeMirror)
                if ftype in ["html", "markdown"]:
                    await asyncio.sleep(0.05)

                options_map = field_config.get("options", {})
                parent_val = widgets[parent].value if parent in widgets else None
                widget = widgets.get(child)
                if widget is None:
                    return
                if ftype == "select":
                    if isinstance(options_map, dict):
                        widget.options = options_map.get(parent_val, [])
                    elif isinstance(options_map, list):
                        widget.options = options_map
                    else:
                        widget.options = []

                    # Special handling for nested data sources like parent_names
                    options_source = field_config.get("options_source")
                    if options_source and options_source in data_sources:
                        data = data_sources[options_source]
                        if isinstance(data, dict) and parent_val in data:
                            if field_config.get("name") == "parent_name":
                                # Special handling for parent_name field - needs work_item_type
                                work_item_type_widget = widgets.get("work_item_type")
                                if (
                                    work_item_type_widget
                                    and work_item_type_widget.value
                                ):
                                    work_item_type = work_item_type_widget.value
                                    customer_data = data.get(parent_val, {})
                                    if isinstance(customer_data, dict):
                                        widget.options = customer_data.get(
                                            work_item_type, []
                                        )
                                    else:
                                        widget.options = []
                                else:
                                    widget.options = []
                            else:
                                # Regular nested handling
                                nested_data = data.get(parent_val, [])
                                widget.options = (
                                    nested_data if isinstance(nested_data, list) else []
                                )

                    # Set default value from default_source if available
                    default_source = field_config.get("default_source")
                    if default_source and default_source in data_sources:
                        default_map = data_sources[default_source]
                        if isinstance(default_map, dict) and parent_val in default_map:
                            widget.value = default_map[parent_val]

                    widget.update()
                elif ftype == "input":
                    if isinstance(options_map, dict):
                        widget.value = options_map.get(parent_val, "")
                    elif isinstance(options_map, list):
                        widget.value = options_map[0] if options_map else ""
                    widget.update()
                elif ftype == "number":
                    if isinstance(options_map, dict):
                        val = options_map.get(parent_val, 0)
                        if isinstance(val, list):
                            widget.value = (
                                val[0]
                                if val and isinstance(val[0], (int, float))
                                else 0
                            )
                        else:
                            widget.value = val if isinstance(val, (int, float)) else 0
                    elif isinstance(options_map, list):
                        widget.value = (
                            options_map[0]
                            if options_map and isinstance(options_map[0], (int, float))
                            else 0
                        )
                    else:
                        widget.value = 0
                    widget.update()
                elif ftype == "chip_group":
                    options = []
                    if isinstance(options_map, dict):
                        options = options_map.get(parent_val, [])
                    elif isinstance(options_map, list):
                        options = options_map
                    # Rebuild chips
                    if isinstance(widget, list) and widget:
                        with widget[0].parent:
                            for chip in widget:
                                chip.delete()
                            chips = []
                            for tag in options:
                                chips.append(
                                    ui.chip(
                                        tag.name,
                                        selectable=True,
                                        icon=tag.icon,
                                        color=tag.color,
                                    )
                                )
                            widgets[child] = chips
                elif ftype == "markdown":
                    # Update markdown preview content when parent changes.
                    # Prefer updating the preview widget if present (stored as child + '_preview').
                    preview_widget = widgets.get(f"{child}_preview") or widgets.get(
                        child
                    )
                    if preview_widget is None:
                        return
                    text = str(parent_val) if parent_val is not None else ""
                    for fn in (
                        getattr(preview_widget, "set_content", None),
                        getattr(preview_widget, "set_markdown", None),
                        getattr(preview_widget, "set_text", None),
                        # fallback: some preview widgets support .value
                        None,
                    ):
                        if callable(fn):
                            try:
                                fn(text)
                                return
                            except Exception:
                                continue
                    # last resort: set value if available
                    if hasattr(preview_widget, "value"):
                        preview_widget.value = text
                        try:
                            preview_widget.update()
                        except Exception:
                            pass
                elif ftype == "html":
                    # Update HTML preview content when parent changes with optional render function
                    if widget is None:
                        return

                    # Get the parent widget to read its value
                    parent_widget = widgets.get(parent)
                    if parent_widget is None:
                        return

                    text = (
                        str(parent_widget.value)
                        if parent_widget.value is not None
                        else ""
                    )

                    # Check if there's a render function specified
                    render_func_name = field_config.get("render_function")
                    if render_func_name and render_func_name in render_functions:
                        # Use the render function to process the text
                        rendered_html = render_functions[render_func_name](text)
                        widget.set_content(rendered_html)
                    else:
                        # Direct HTML update
                        widget.set_content(text)

            return update_child

        # Attach listener if parent exists.
        # Try several possible event names (NiceGUI components differ across versions)
        # and fall back to a lightweight polling timer if none of them attach.
        if parent in widgets:
            parent_widget = widgets[parent]
            attached = False
            if hasattr(parent_widget, "on"):
                for event_name in ("update:model-value", "update", "change", "input"):
                    try:
                        parent_widget.on(event_name, make_update_child())
                        attached = True
                        # Don't break - try to attach multiple events for better coverage
                    except Exception:
                        # ignore and try next event name
                        continue
            # If we couldn't attach an event listener, consider using polling as a fallback.
            # Only enable the polling fallback when the child explicitly allows it via
            # 'parent_update: true' (default True). This prevents polling-based auto-updates
            # when the field has 'parent_update: false'. Event-driven wiring is still attempted
            # regardless of this flag.
            # Also use polling for html/markdown children as they may need more reliable updates
            child_ftype = field_config.get("type")
            needs_polling = child_ftype in ["html", "markdown"]

            if not attached or needs_polling:
                if field_config.get("parent_update", False):
                    try:
                        last = {"value": getattr(parent_widget, "value", None)}

                        async def _poll_parent():
                            try:
                                v = getattr(parent_widget, "value", None)
                            except Exception:
                                v = None
                            if v != last["value"]:
                                last["value"] = v
                                # call update handler (it reads current parent value from widgets)
                                try:
                                    await make_update_child()(None)
                                except Exception:
                                    pass

                        ui.timer(callback=_poll_parent, interval=0.25)
                    except Exception:
                        # If even polling fails, we can't wire this parent — leave it unbound.
                        pass


# ===== DATAFRAME UTILITIES =====


def filter_df(df, filters=None, return_as="df", column=None):
    """Filter dataframe and return in various formats.

    Args:
        df: DataFrame to filter
        filters: Dict of column:value pairs to filter by (None = no filtering)
        return_as: Output format - "df", "list", "distinct_list", or "unique"
        column: Column name to return when return_as is "list", "distinct_list", or "unique"

    Returns:
        Filtered data in requested format
    """
    # Handle the case where we just want unique values without filtering
    if filters is None or len(filters) == 0:
        if return_as in ["distinct_list", "unique"] and column:
            if column in df.columns:
                return df[column].dropna().unique().tolist()
            return []
        elif return_as == "list" and column:
            if column in df.columns:
                return df[column].tolist()
            return []
        return df

    # Apply filters
    mask = None
    for col, val in filters.items():
        # Handle list values with .isin() instead of ==
        if isinstance(val, list):
            current_mask = df[col].isin(val)
        else:
            current_mask = df[col] == val

        if mask is None:
            mask = current_mask
        else:
            mask &= current_mask
    filtered = df.loc[mask] if mask is not None else df

    if return_as == "list" and column:
        return filtered[column].tolist()
    elif return_as in ["distinct_list", "unique"] and column:
        return filtered[column].unique().tolist()
    return filtered


# Deprecated: Use filter_df(df, filters=None, return_as="unique", column=column_name) instead
def get_unique_list(df, column):
    """Get unique values from a column.

    DEPRECATED: Use filter_df(df, filters=None, return_as="unique", column=column_name) instead.
    This function is kept for backward compatibility.
    """
    return filter_df(df, filters=None, return_as="unique", column=column)


# ===== CONFIGURATION HELPERS =====


def assign_dynamic_options(fields, data_sources):
    for field in fields:
        if field.get("type") in ["date"] and "options_source" in field:
            options_source = field["options_source"]
            if options_source == "today":
                field["options"] = [str(date.today())]
        elif "options" in field and "options_source" in field:
            source = field["options_source"]
            # Handle nested data sources (like parent_names)
            data = data_sources.get(source, [])
            if isinstance(data, dict) and not data:
                # Empty dict, set empty options
                field["options"] = []
            elif isinstance(data, dict):
                # For nested structures like parent_names, we'll handle this during parent binding
                field["options"] = []
            else:
                field["options"] = data

        if field.get("type") in ["number"]:
            val = field.get("options", 0)
            if isinstance(val, (np.integer, float)):
                field["options"] = int(val)
            elif isinstance(val, int):
                field["options"] = val
            elif val is None:
                field["options"] = 0

        if "default_source" in field:
            default_source = field["default_source"]
            field["default"] = data_sources.get(default_source, None)


# DEPRECATED: Use build_generic_tab_panel directly instead
def make_tab_panel(tab_name, title, build_fn, width: str = "2"):
    """Create a tab panel with a card container.

    DEPRECATED: This function creates unnecessary nested cards.
    Use build_generic_tab_panel() directly instead, which already creates its own card.

    This function is kept for backward compatibility but should not be used in new code.
    """
    with ui.tab_panel(tab_name):
        with ui.card().classes(f"w-full max-w-{width}xl mx-auto my-0 p-4"):
            ui.label(title).classes("text-h5 mb-2")
            build_fn()


# ===== WIDGET VALUE PARSING =====


def parse_widget_values(widgets: dict) -> dict:
    """Extract values from widget instances.

    Args:
        widgets: Dictionary of widget instances

    Returns:
        Dictionary mapping widget names to their values
    """
    result = {}
    for key, widget in widgets.items():
        # Chip group: list of chips, get selected ones
        if isinstance(widget, list) and widget and hasattr(widget[0], "selected"):
            result[key] = [
                chip.text for chip in widget if getattr(chip, "selected", False)
            ]
        # Switch
        elif hasattr(widget, "value") and hasattr(widget, "set_value"):
            result[key] = widget.value
        # Select/Input/Textarea
        elif hasattr(widget, "value"):
            result[key] = widget.value
        else:
            result[key] = None
    return result


def get_ui_elements(config: dict) -> list[str]:
    elements = []
    for key, value in config.items():
        if isinstance(value, dict) and "fields" in value and "action" in value:
            elements.append(key)

    return elements


# ===== UI RENDERING HELPERS =====


def render_markdown_card(filename):
    # Look in docs/ directory for documentation files
    file_path = os.path.join(os.path.dirname(__file__), "..", "docs", filename)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        content = f"Error reading {filename}: {e}"
    with ui.card().classes("w-full h-full my-4 p-0 flex flex-col"):
        ui.markdown(content).classes("flex-1 w-full h-full p-6 overflow-auto")


# ===== GENERIC TAB PANEL BUILDERS =====


def add_generic_save_button(
    save_data, fields, widgets, custom_handlers=None, on_success_callback=None
):
    """
    Generic save button that handles both standard DB operations and custom handlers.

    Args:
        save_data: SaveData object with function name and display info
        fields: List of field configs
        widgets: Dict of widget instances
        custom_handlers: Optional dict mapping function names to handler functions
        on_success_callback: Optional async callback to run after successful save
    """

    async def on_save():
        # Import globals from the global registry
        from .globals import GlobalRegistry

        LOG = GlobalRegistry.get("LOG")
        QE = GlobalRegistry.get("QE")
        DO = GlobalRegistry.get("DO")

        if not QE:
            ui.notify("Query engine not initialized", color="negative")
            return

        required_fields = [f["name"] for f in fields if not f.get("optional", False)]
        if not check_input(widgets, required_fields):
            return

        func_name = save_data.function

        # Check if this is a custom handler (e.g., DevOps operations)
        if custom_handlers and func_name in custom_handlers:
            handler = custom_handlers[func_name]
            # Check if handler is async
            import asyncio

            if asyncio.iscoroutinefunction(handler):
                state, msg = await handler(widgets=widgets)
            else:
                state, msg = handler(widgets=widgets)
            col = "positive" if state else "negative"
            ui.notify(msg, color=col)
            if state and on_success_callback:
                await on_success_callback()
            return

        # Standard database operation
        kwargs = {f["name"]: widgets[f["name"]].value for f in fields}
        # Convert any single-item list in kwargs to a string
        for k, v in kwargs.items():
            if isinstance(v, list):
                if len(v) == 1:
                    kwargs[k] = v[0]
                elif len(v) > 1:
                    raise ValueError(
                        f"Field '{k}' has multiple values: {v}. Only one value is allowed."
                    )

        await QE.function_db(func_name, **kwargs)

        # If customer add/update, regenerate DevOps table
        if func_name in ["insert_customer", "update_customer"]:
            if DO:
                if LOG:
                    LOG.log_msg("INFO", "Regenerating DevOps data...")
                ui.notify(
                    "Regenerating DevOps data... This may take a few moments.",
                    color="info",
                )
                await DO.update_devops(incremental=True)

        msg_1, msg_2 = print_success(
            save_data.main_action,
            widgets[save_data.main_param].value,
            save_data.secondary_action,
            widgets=widgets,
        )
        if LOG:
            LOG.log_msg("INFO", msg_1)
            LOG.log_msg("INFO", msg_2)

        if on_success_callback:
            await on_success_callback()

    ui.button(save_data.button_name, on_click=on_save).classes("mt-2")


def build_generic_tab_panel(
    entity_name,
    tab_type,
    container_dict,
    config_source,
    data_prep_func=None,
    custom_handlers=None,
    layout_builder=None,
    on_success_callback=None,
    render_functions=None,
    container_size="md",
):
    """
    Generic tab panel builder that handles all common logic.

    Args:
        entity_name: Name of entity in config (e.g., "customer", "project")
        tab_type: Type of tab (e.g., "Add", "Update", "Disable")
        container_dict: Dictionary storing tab containers
        config_source: The config dict to use (config_ui or config_devops_ui)
        data_prep_func: Optional function to prepare data sources
        custom_handlers: Optional dict of custom save handlers
        layout_builder: Optional custom layout building function
        on_success_callback: Optional async callback after successful save
        render_functions: Optional dict of render functions for html type fields
        container_size: Container size name from UI_STYLES (e.g., "xs", "sm", "md", "lg", "xl", "xxl", "full")

    Returns:
        widgets: Dictionary of created widget instances
    """

    # Container management
    container = container_dict.get(tab_type)
    if container is None:
        container = ui.element()
        container_dict[tab_type] = container
    container.clear()

    # Load config
    entity_config = config_source[entity_name][tab_type.lower()]
    fields = entity_config["fields"]
    action = entity_config["action"]

    # Get container width from styling config
    max_width = UI_STYLES.get_container_width(container_size)
    card_classes = f"{UI_STYLES.get_layout_classes('card')} max-w-{max_width}xl"

    with container:
        with ui.card().classes(card_classes):
            # Prepare data sources
            data_sources = {}
            if data_prep_func:
                data_sources = data_prep_func(tab_type, fields)

            # Assign dynamic options
            if data_sources:
                assign_dynamic_options(fields, data_sources=data_sources)

            # Build layout based on YAML structure
            widgets = {}
            rows_config = entity_config.get("rows")
            columns_config = entity_config.get("columns")
            pending_relations = []

            if rows_config:
                # Layout with multiple rows
                # First pass: check if ANY row has wide widgets using UI_STYLES
                has_wide_layout = False
                for row_fields in rows_config:
                    for field_name in row_fields:
                        field_config = next(
                            (f for f in fields if f["name"] == field_name), None
                        )
                        if field_config and UI_STYLES.is_wide_widget(
                            field_config.get("type")
                        ):
                            has_wide_layout = True
                            break
                    if has_wide_layout:
                        break

                with ui.column().classes(UI_STYLES.get_layout_classes("form_column")):
                    for row_fields in rows_config:
                        # Get field configs for this row, preserving the order from row_fields
                        row_field_configs = []
                        for field_name in row_fields:
                            field_config = next(
                                (f for f in fields if f["name"] == field_name), None
                            )
                            if field_config:
                                row_field_configs.append(field_config)

                        is_single_field = len(row_field_configs) == 1

                        with ui.row().classes(UI_STYLES.get_layout_classes("form_row")):
                            # Determine widget size based on layout mode
                            if has_wide_layout or is_single_field:
                                # Wide layout mode: all widgets use full width with flex
                                widget_size = "full"
                            else:
                                # Standard layout mode: widgets use their default sizes
                                widget_size = None  # Will be determined per widget type

                            _, rels = make_input_row(
                                row_field_configs,
                                layout_mode=widget_size,
                                widgets=widgets,
                                defer_parent_wiring=True,
                                render_functions=render_functions,
                            )
                            pending_relations.extend(rels)
            elif columns_config:
                # Layout with multiple columns
                with ui.row():
                    for col_fields in columns_config:
                        with ui.column():
                            # Get field configs for this column, preserving the order from col_fields
                            col_field_configs = []
                            for field_name in col_fields:
                                field_config = next(
                                    (f for f in fields if f["name"] == field_name), None
                                )
                                if field_config:
                                    col_field_configs.append(field_config)

                            _, rels = make_input_row(
                                col_field_configs,
                                widgets=widgets,
                                defer_parent_wiring=True,
                                render_functions=render_functions,
                            )
                            pending_relations.extend(rels)
            elif layout_builder:
                # Custom layout builder (fallback for complex cases)
                widgets = layout_builder(fields, entity_config)
            else:
                # Default simple column layout
                with ui.column():
                    make_input_row(
                        fields, widgets=widgets, render_functions=render_functions
                    )

            # Bind parent relations if we deferred them
            if pending_relations:
                bind_parent_relations(
                    widgets, pending_relations, render_functions, data_sources
                )

            # Add save button
            save_data = SaveData(**action)
            add_generic_save_button(
                save_data, fields, widgets, custom_handlers, on_success_callback
            )

    return widgets
