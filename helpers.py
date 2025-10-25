import os
from nicegui import ui
from datetime import date, timedelta
import re
import numpy as np


def get_range_for(option):
    today = date.today()
    if option == "Day":
        return f"{today} - {today}"
    elif option == "Week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return f"{start} - {end}"
    elif option == "Month":
        start = today.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
        return f"{start} - {end}"
    elif option == "Year":
        start = today.replace(month=1, day=1)
        end = today.replace(month=12, day=31)
        return f"{start} - {end}"
    elif option == "All-Time":
        # Set to some default, or leave blank
        start = date(2000, 1, 1)  ## TODO min(start_date) in db
        end = today
        return f"{start} - {end}"
    else:
        return ""


def parse_date_range(date_range_str):
    # Accepts formats like 'YYYYMMDD - YYYYMMDD' or 'YYYY-MM-DD - YYYY-MM-DD'
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


def check_input(widgets, required_fields) -> bool:
    is_ok = True
    for field in required_fields:
        if not widgets[field].value:
            ui.notify(
                f"{field.replace('_', ' ').title()} is required!",
                color="negative",
            )
            is_ok = False
    return is_ok


def print_success(table: str, main_param: str, action_type: str, widgets: dict = None):
    msg_1 = f"{table} {main_param} {action_type}!"
    ui.notify(
        msg_1,
        color="positive",
    )
    if widgets:
        print_msg = "Parameters: "
        for field in widgets:
            print_msg += f"{field}: {widgets[field].value}, "
        print_msg = print_msg.rstrip(", ")
        return msg_1, print_msg
    return msg_1, "No data to display."


def extract_table_name(query_text: str) -> str:
    match = re.search(r"from\s+([^\s;]+)", query_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "unknown_table"


def extract_devops_id(text):
    match = re.search(r":\s*(\d+)\s*-", text)
    if match:
        return int(match.group(1))
    return None


def date_input(label, input_width: str = "w-64"):
    with ui.input(label).props("readonly").classes(input_width) as date:
        with ui.menu().props("no-parent-event") as menu:
            with ui.date().bind_value(date):
                with ui.row().classes("justify-end"):
                    ui.button("Close", on_click=menu.close).props("flat")
        with date.add_slot("append"):
            ui.icon("edit_calendar").on("click", menu.open).classes("cursor-pointer")
    return date


def make_input_row(
    fields,
    input_width: str = "w-64",
    widgets: dict = None,
    defer_parent_wiring: bool = False,
):
    """Create UI widgets for a list of field configs.

    If `widgets` is provided it will be updated with the created widgets.
    If `defer_parent_wiring` is True the function will NOT attach parent->child
    listeners. Instead it returns a tuple (created_widgets, pending_relations)
    where pending_relations is a list of dicts describing relations to bind
    later via `bind_parent_relations(widgets, pending_relations)`.
    """
    created = {}
    pending_relations = []

    def _double_width_class(wclass: str) -> str:
        """Convert a 'w-<num>' class to a fixed min-width style string.

        Returns a style fragment like 'min-width:512px' for numeric classes.
        For 'w-full' or non-matching classes returns empty string so layout classes remain.
        """
        if not wclass:
            return ""
        if wclass.strip() == "w-full":
            return ""
        m = __import__("re").match(r"w-(\d+)$", wclass)
        if m:
            try:
                val = int(m.group(1))
                # heuristic mapping: 8px per unit to create a readable min-width
                px = val * 8
                return f"min-width:{px}px"
            except Exception:
                return ""
        return ""

    for field in fields:
        label = field["label"]
        if field.get("optional", True):
            label += " (optional)"

        ftype = field["type"]
        fname = field["name"]

        default_val = field.get("default")
        options_val = field.get("options")
        # Use options for default if present and not None
        if options_val is not None:
            if isinstance(options_val, list) and options_val:
                default_val = options_val[0]
            elif isinstance(options_val, (str, int, float)):
                default_val = options_val

        if ftype == "input":
            created[fname] = ui.input(label).classes(input_width)
            if default_val is not None:
                created[fname].value = default_val
        elif ftype == "text":
            created[fname] = ui.textarea(label).classes(input_width)
            if default_val is not None:
                created[fname].value = default_val
        elif ftype == "number":
            created[fname] = ui.number(label, min=0).classes(input_width)
            if default_val is not None:
                created[fname].value = default_val
        elif ftype == "date":
            created[fname] = date_input(label, input_width=input_width)
            if default_val is not None:
                created[fname].value = default_val
        elif ftype == "datetime":
            created[fname] = ui.input(label, placeholder="YYYY-MM-DD HH:MM:SS").classes(
                input_width
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
            select_widget = ui.select(options, label=label, with_input=True).classes(
                input_width
            )
            if "default" in field:
                select_widget.value = field["default"]
            created[fname] = select_widget
        elif ftype == "switch":
            created[fname] = ui.switch(text=label).classes(input_width)
            if "default" in field:
                created[fname].value = field["default"]
        elif ftype == "chip_group":
            chips = []
            with ui.row().classes(f"mb-4 {input_width} gap-1"):
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
            editor = ui.codemirror(
                default_val or "",
                language=field.get("type_language", "markdown"),
                theme="dracula",
            )
            # Keep layout classes so the parent row can control placement, but add a
            # min-width inline style so the editor doesn't expand indefinitely.
            editor.classes(input_width)
            width_style = _double_width_class(input_width)
            if width_style:
                editor.style(width_style)
            created[fname] = editor
        elif ftype == "markdown":
            # Keep layout classes for row placement and add a min-width style so preview
            # remains a readable fixed width but still participates in flex layout.
            width_style = _double_width_class(input_width)
            if width_style:
                preview = (
                    ui.markdown(default_val or "")
                    .classes(input_width)
                    .style(width_style)
                )
            else:
                preview = ui.markdown(default_val or "").classes(input_width)
            created[fname] = preview
            created[f"{fname}_preview"] = preview

    # Merge created into provided widgets (if any)
    out_widgets = widgets if widgets is not None else {}
    # If widgets was None, ensure it's a new dict
    if widgets is None:
        out_widgets = created
    else:
        out_widgets.update(created)

    # Collect pending parent relations
    for field in fields:
        if "parent" in field:
            pending_relations.append(
                {
                    "child": field["name"],
                    "parent": field["parent"],
                    "field_config": field,
                }
            )

    if defer_parent_wiring:
        return out_widgets, pending_relations

    # Otherwise bind relations immediately (backwards compatible behavior)
    bind_parent_relations(out_widgets, pending_relations)
    return out_widgets


def bind_parent_relations(widgets: dict, pending_relations: list):
    """Bind parent->child update handlers for pending relations.

    `pending_relations` is a list of dicts with keys: child, parent, field_config
    """
    for rel in pending_relations:
        child = rel["child"]
        parent = rel["parent"]
        field_config = rel.get("field_config", {})

        def make_update_child(child=child, parent=parent, field_config=field_config):
            def update_child(e):
                options_map = field_config.get("options", {})
                parent_val = widgets[parent].value if parent in widgets else None
                widget = widgets.get(child)
                ftype = field_config.get("type")
                if widget is None:
                    return
                if ftype == "select":
                    if isinstance(options_map, dict):
                        widget.options = options_map.get(parent_val, [])
                    elif isinstance(options_map, list):
                        widget.options = options_map
                    else:
                        widget.options = []
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
                    except Exception:
                        # ignore and try next event name
                        continue
            # If we couldn't attach an event listener, consider using polling as a fallback.
            # Only enable the polling fallback when the child explicitly allows it via
            # 'parent_update: true' (default True). This prevents polling-based auto-updates
            # when the field has 'parent_update: false'. Event-driven wiring is still attempted
            # regardless of this flag.
            if not attached:
                if field_config.get("parent_update", False):
                    try:
                        last = {"value": getattr(parent_widget, "value", None)}

                        def _poll_parent():
                            try:
                                v = getattr(parent_widget, "value", None)
                            except Exception:
                                v = None
                            if v != last["value"]:
                                last["value"] = v
                                # call update handler (it reads current parent value from widgets)
                                try:
                                    make_update_child()(None)
                                except Exception:
                                    pass

                        ui.timer(callback=_poll_parent, interval=0.25)
                    except Exception:
                        # If even polling fails, we can't wire this parent — leave it unbound.
                        pass


def filter_df(df, filters, return_as="df", column=None):
    mask = None
    for col, val in filters.items():
        if mask is None:
            mask = df[col] == val
        else:
            mask &= df[col] == val
    filtered = df.loc[mask] if mask is not None else df
    if return_as == "list" and column:
        return filtered[column].tolist()
    elif return_as == "distinct_list" and column:
        return filtered[column].unique().tolist()
    return filtered


def get_unique_list(df, column):
    if column in df.columns:
        return df[column].dropna().unique().tolist()
    return []


def assign_dynamic_options(fields, data_sources):
    for field in fields:
        if field.get("type") in ["date"] and "options_source" in field:
            options_source = field["options_source"]
            if options_source == "today":
                field["options"] = [str(date.today())]
        elif "options" in field and "options_source" in field:
            source = field["options_source"]
            field["options"] = data_sources.get(source, [])

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


def make_tab_panel(tab_name, title, build_fn, width: str = "2"):
    with ui.tab_panel(tab_name):
        with ui.card().classes(f"w-full max-w-{width}xl mx-auto my-0 p-4"):
            ui.label(title).classes("text-h5 mb-2")
            build_fn()


def parse_widget_values(widgets):
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


def render_markdown_card(filename):
    file_path = os.path.join(os.path.dirname(__file__), filename)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        content = f"Error reading {filename}: {e}"
    with ui.card().classes("w-full h-full my-4 p-0 flex flex-col"):
        ui.markdown(content).classes("flex-1 w-full h-full p-6 overflow-auto")
