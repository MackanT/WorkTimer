"""
Shared helper utilities: dates, validation, text parsing, widget values,
and dynamic form-config plumbing.

Styling lives in ui_styles.py and markdown rendering in markdown_utils.py —
both are re-exported here so existing imports (and config `render_function:`
lookups, which resolve names on this module) keep working.

Note: the legacy form factory (make_input_row + bind_parent_relations and its
_update_*/_execute_dynamic_query family, ~700 lines) was removed — all forms
now render through src/ui/dynamic_widgets.py, and the only remaining callers
were dead fallback paths.
"""

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd
from nicegui import ui

# Re-exports for backward compatibility (many modules import these from helpers)
from .ui_styles import UIStyles, UI_STYLES  # noqa: F401
from .markdown_utils import (  # noqa: F401
    MARKDOWN_DARK_MODE_CSS,
    render_and_sanitize_markdown,
    convert_html_to_markdown,
)


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
        # Fallback range only — the time-tracking page overrides the start
        # with min(start_time) from the database when this option is picked.
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


def token_expiry_level(expires, today: date | None = None):
    """Classify a tracker token's expiry date for the startup warning.

    Returns (level, days_left) where level is "expired" (past), "critical"
    (≤ 7 days), "warning" (≤ 30 days) or "ok" — or None when the value
    isn't a parseable YYYY-MM-DD date.
    """
    try:
        exp = date.fromisoformat(str(expires).strip()[:10])
    except (ValueError, TypeError):
        return None
    days = (exp - (today or date.today())).days
    if days < 0:
        return ("expired", days)
    if days <= 7:
        return ("critical", days)
    if days <= 30:
        return ("warning", days)
    return ("ok", days)


# ===== DATA VALIDATION =====


def has_dataframe_data(df: pd.DataFrame | None) -> bool:
    """
    Check if a DataFrame has data (not None and not empty).

    Args:
        df: DataFrame to check (can be None)

    Returns:
        True if df has data, False if None or empty
    """
    return df is not None and not df.empty


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

        # Get widget value safely
        widget_value = _get_widget_value(widget)

        # Check if the widget has a value. Treat 0 and False as valid values.
        missing = False
        if widget_value is None:
            missing = True
        elif isinstance(widget_value, str) and widget_value.strip() == "":
            missing = True
        elif isinstance(widget_value, (list, tuple)) and len(widget_value) == 0:
            missing = True

        if missing:
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
    """Extract table name from SQL query.

    Args:
        query_text: SQL query string

    Returns:
        Table name or "unknown_table" if not found
    """
    match = re.search(r"from\s+([^\s;]+)", query_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "unknown_table"


def extract_id_from_text(
    text: str, pattern: str = r":\s*(\d+)\s*-", group: int = 1
) -> int | None:
    """
    Extract numeric ID from text using a regex pattern.

    Generic utility for extracting IDs from formatted strings like:
    - "Epic: 123 - Description" (default pattern)
    - "ID: 456" (pattern r"ID:\s*(\d+)")
    - "[#789]" (pattern r"\[#(\d+)\]")

    Args:
        text: Text to search for ID
        pattern: Regex pattern with a capture group for the ID (default: ': ID -')
        group: Which capture group contains the ID (default: 1)

    Returns:
        Extracted ID as integer, or None if not found

    Examples:
        >>> extract_id_from_text("Epic: 123 - My Epic")
        123
        >>> extract_id_from_text("Task #456", pattern=r"#(\d+)")
        456
    """
    if not text or not isinstance(text, str):
        return None

    try:
        match = re.search(pattern, text)
        if match:
            return int(match.group(group))
    except (ValueError, IndexError, AttributeError):
        return None

    return None


def extract_devops_id(text: str) -> int | None:
    """
    Extract DevOps ID from text containing pattern ': ID -'.

    Convenience wrapper for extract_id_from_text() with DevOps-specific pattern.

    Args:
        text: Text to search for DevOps ID (e.g., "Epic: 123 - Description")

    Returns:
        Extracted ID as integer, or None if not found
    """
    return extract_id_from_text(text, pattern=r":\s*(\d+)\s*-")


# ===== WIDGET VALUE HELPERS =====


def _get_widget_value(widget):
    """Extract value from a widget instance safely.

    Args:
        widget: Widget instance (can be single widget, chip group list, etc.)

    Returns:
        Widget value (string, number, boolean, list, etc.) or None
    """
    if widget is None:
        return None

    # Handle chip groups (list of chips) — return the selected texts, matching
    # parse_widget_values (an empty list reads as "missing" in check_input).
    if isinstance(widget, list) and widget and hasattr(widget[0], "selected"):
        return [chip.text for chip in widget if getattr(chip, "selected", False)]

    # Handle widgets with value attribute
    if hasattr(widget, "value"):
        return widget.value

    return None


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
        # Anything with a value (switch/select/input/textarea/wrapper)
        elif hasattr(widget, "value"):
            result[key] = widget.value
        else:
            result[key] = None
    return result


# ===== FORM CONFIG PLUMBING =====

# {{placeholder}} syntax for description templates. Friendlier aliases map
# to the real form-field names ({{contact}} == {{contact_person}}).
_TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_TEMPLATE_ALIASES = {"contact": "contact_person", "date": "today"}


def _canon_placeholder(name: str) -> str:
    return _TEMPLATE_ALIASES.get(name, name)


def fill_template(template: str, values: dict) -> str:
    """Replace {{field}} placeholders (and the legacy single-brace {today} /
    {field} forms) with values. 'today' is always available; an UNKNOWN
    {{placeholder}} stays literal, so a typo is visible instead of silently
    vanishing."""
    vals = {"today": str(date.today())}
    for k, v in (values or {}).items():
        vals[k] = "" if v is None else str(v)

    def _sub(m: re.Match) -> str:
        return vals.get(_canon_placeholder(m.group(1)), m.group(0))

    out = _TEMPLATE_PLACEHOLDER_RE.sub(_sub, template or "")
    for k, v in vals.items():
        out = out.replace("{" + k + "}", v)
    return out


def template_has_field(template: str, field_name: str) -> bool:
    """True when the raw template carries a {{placeholder}} resolving to
    `field_name` (aliases included)."""
    return any(
        _canon_placeholder(n) == field_name
        for n in _TEMPLATE_PLACEHOLDER_RE.findall(template or "")
    )


def sync_template_text(text: str, raw_template: str, values: dict) -> str:
    """Refresh every placeholder-carrying line of `text` from the RAW
    template with the current `values`.

    Each raw line with at least one {{placeholder}} is located in `text` by
    its literal parts (every placeholder wildcarded — so multiple
    placeholders per line, moved lines and relabelled lines all work), then
    replaced with the freshly rendered line. A line with no literal text at
    all can't be found again once values replaced it and is skipped — keep
    some label text on placeholder lines."""
    out = text or ""
    for raw_line in (raw_template or "").splitlines():
        if not _TEMPLATE_PLACEHOLDER_RE.search(raw_line):
            continue
        # split() with the capturing group interleaves [lit, name, lit, …]
        literals = _TEMPLATE_PLACEHOLDER_RE.split(raw_line)[0::2]
        if not any(lit.strip() for lit in literals):
            continue  # nothing to anchor on
        pattern = re.compile(
            "^" + ".*".join(re.escape(lit) for lit in literals) + "$",
            re.MULTILINE,
        )
        m = pattern.search(out)
        if m is None:
            continue
        out = out[: m.start()] + fill_template(raw_line, values) + out[m.end():]
    return out


def setup_template_handling(widgets: dict) -> None:
    """Wire the description editor's per-type templates to the form.

    A type change reloads the template through fill_template ({{today}},
    {{source}}, {{contact_person}}, …). A dropdown change re-renders the
    placeholder-carrying lines from the raw template with the current
    values (sync_template_text) — position-independent, so templates can be
    rearranged and relabelled freely, with several placeholders per line.
    Templates without a placeholder for a field fall back to the legacy
    hardcoded **Source:** / **Contact:** line convention.
    """
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

            values = {
                f: (widgets[f].value if widgets.get(f) is not None else "")
                for f in parent_fields
            }

            if parent_field_changed:
                if parent_field_changed not in parent_fields:
                    continue
                template_content = templates.get(current_type, "")
                text = widget.value or ""
                if template_has_field(template_content, parent_field_changed):
                    # Re-render the placeholder-carrying lines from the raw
                    # template with the CURRENT dropdown values.
                    widget.value = sync_template_text(
                        text, template_content, values
                    )
                else:
                    # Legacy templates without a {{placeholder}}: the old
                    # hardcoded label-line convention.
                    parent_widget = widgets.get(parent_field_changed)
                    value = str(
                        (parent_widget.value if parent_widget is not None else "")
                        or ""
                    )
                    label = {
                        "source": "**Source:**",
                        "contact_person": "**Contact:**",
                    }.get(parent_field_changed)
                    if label:
                        lines = text.split("\n")
                        for i, line in enumerate(lines):
                            if label in line:
                                lines[i] = f"{label} {value}"
                                break
                        widget.value = "\n".join(lines)
            else:
                # Full template reload (only when work_item_type changes).
                template_content = templates.get(current_type, "")
                if template_content:
                    widget.value = fill_template(template_content, values)

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


def assign_dynamic_options(fields: list, data_sources: dict) -> None:
    """Assign dynamic options to fields based on data sources.

    Args:
        fields: List of field configuration dicts (pass a deep copy — this
            mutates the dicts in place)
        data_sources: Dictionary of data sources for options
    """
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
                # For nested structures (parent-child relationships):
                # Store the dict in options so parent binding can access it
                field["options"] = data
            else:
                field["options"] = data

        if field.get("type") in ["number"]:
            val = field.get("options", 0)
            # If options is a dict (parent-child relationship), keep it as is
            if isinstance(val, dict):
                pass  # Keep the dict for parent handler
            elif isinstance(val, (np.integer, float)):
                field["options"] = int(val)
            elif isinstance(val, int):
                field["options"] = val
            elif val is None:
                field["options"] = 0

        # Note: default_source is handled by parent-child binding, not here
