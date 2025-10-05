from nicegui import ui
from datetime import date, timedelta
import re


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


def make_input_row(fields, input_width: str = "w-64"):
    widgets = {}
    for field in fields:
        label = field["label"]
        if field.get("optional", True):
            label += " (optional)"

        ftype = field["type"]
        fname = field["name"]

        if ftype == "input":
            widgets[fname] = ui.input(label).classes(input_width)
        elif ftype == "text":
            widgets[fname] = ui.textarea(label).classes(input_width)
        elif ftype == "number":
            widgets[fname] = ui.number(label, min=0).classes(input_width)
        elif ftype == "date":
            widgets[fname] = date_input(label, input_width=input_width)
            if "default" in field:
                widgets[fname].value = field["default"]
        elif ftype == "select":
            if "parent" in field:
                options = []
            else:
                options = field.get("options", {})
            select_widget = ui.select(options, label=label).classes(input_width)
            if "default" in field:
                select_widget.value = field["default"]
            widgets[fname] = select_widget
        elif ftype == "switch":
            widgets[fname] = ui.switch(text=label).classes(input_width)
            if "default" in field:
                widgets[fname].value = field["default"]
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
            widgets[fname] = chips

    # Generalize parent-child relation for any widget type
    for field in fields:
        if "parent" in field:
            child = field["name"]
            parent = field["parent"]

            def update_child(e, child=child, parent=parent):
                field_config = next((f for f in fields if f["name"] == child), None)
                options_map = field_config.get("options", {}) if field_config else {}
                parent_val = widgets[parent].value
                # Update child widget based on its type
                widget = widgets[child]
                ftype = field_config.get("type") if field_config else None
                if ftype == "select":
                    if isinstance(options_map, dict):
                        widget.options = options_map.get(parent_val, [])
                    elif isinstance(options_map, list):
                        widget.options = options_map
                    else:
                        widget.options = []
                    widget.update()
                elif ftype == "input":
                    # For input, set value if options_map is dict/list
                    if isinstance(options_map, dict):
                        widget.value = options_map.get(parent_val, "")
                    elif isinstance(options_map, list):
                        widget.value = options_map[0] if options_map else ""
                    else:
                        print("If we are ever here, something is wrong!")
                    widget.update()
                elif ftype == "number":
                    # For number, set value if options_map is dict/list
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
                    # For chip_group, update chips if options_map is dict/list
                    chips = []
                    options = []
                    if isinstance(options_map, dict):
                        options = options_map.get(parent_val, [])
                    elif isinstance(options_map, list):
                        options = options_map
                    # Rebuild chips
                    with widget[0].parent:
                        for chip in widget:
                            chip.delete()
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
                # Add more widget types as needed

            widgets[parent].on("update:model-value", update_child)
    return widgets


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
        if "options" in field and "options_source" in field:
            source = field["options_source"]
            field["options"] = data_sources.get(source, [])
        elif field.get("type") in ["date"] and "default" in field:
            default = field["default"]
            if default == "today":
                field["default"] = str(date.today())


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
