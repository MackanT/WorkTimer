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


def extract_table_name(query_text: str) -> str:
    match = re.search(r"from\s+([^\s;]+)", query_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "unknown_table"


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

        if field["type"] == "input":
            widgets[field["name"]] = ui.input(label).classes(input_width)
        elif field["type"] == "number":
            widgets[field["name"]] = ui.number(label, min=0).classes(input_width)
        elif field["type"] == "date":
            widgets[field["name"]] = date_input(label, input_width=input_width)
        elif field["type"] == "select":
            select_widget = ui.select(field["options"], label=label).classes(
                input_width
            )
            if "options_default" in field:
                select_widget.value = field["options_default"]
            widgets[field["name"]] = select_widget
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
        if field.get("type") in ["select", "chip_group"] and "options_source" in field:
            source = field["options_source"]
            field["options"] = data_sources.get(source, [])
        elif field.get("type") in ["date"] and "options_default" in field:
            default = field["options_default"]
            if default == "today":
                field["default"] = str(date.today())
