import dearpygui.dearpygui as dpg
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import time
import threading
from functools import partial

import os
from typing import Literal, Any
import sqlite3
import re

COMBO_WIDTH = 325
INDENT_1 = 15
INDENT_2 = 20

WARNING_RED = [255, 99, 71]
WARNING_GREEN = [34, 139, 34]


dpg.create_context()

## Image Input
width, height, channels, data = dpg.load_image("icon_calendar.png")
with dpg.texture_registry():
    icon_calendar = dpg.add_static_texture(width, height, data)


# Create a dummy pandas DataFrame with customer, project, state, and time info
data = {
    "customer_id": [0, 0, 1, 1, 1],
    "customer_name": [
        "Rowico",
        "Rowico",
        "Random Forest",
        "Random Forest",
        "Random Forest",
    ],
    "project_id": [0, 1, 2, 3, 4],
    "project_name": ["Arbete", "Staffling", "Arbete", "WorkTimer", "Övertid"],
    "initial_state": [True, False, True, False, True],
    "initial_text": ["1 h 30 min", "0 h 0 min", "2 h 0 min", "0 h 0 min", "3 h 15 min"],
    "wage": [100, 100, 1000, 1000, 1000],
}
df = pd.DataFrame(data)
input_focused = False


###
# Help Functions
###


def __get_current_date_struct() -> dict:
    now = datetime.now()
    today_struct = {
        "month_day": now.day,
        "month": now.month - 1,  # zero-indexed
        "year": now.year - 1900,  # offset from 1900
        "hour": 0,
        "min": 0,
        "sec": 0,
    }
    return today_struct


def __format_date_struct(input_struct: dict) -> str:
    year = input_struct["year"] + 1900
    month = input_struct["month"] + 1
    day = input_struct["month_day"]
    return f"{year:04d}-{month:02d}-{day:02d}"


def __is_valid_date(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


###
# UI Functions
###
def update_total_time(customer_id: int, label_value: str) -> None:
    dpg.set_value(f"total_{customer_id}", label_value)


def update_individual_time(customer_id: int, project_id: int, label_value: str) -> None:
    dpg.set_value(f"time_{customer_id}_{project_id}", label_value)


def on_input_focus(sender, app_data) -> None:
    global input_focused
    input_focused = True


def on_input_unfocus(sender, app_data) -> None:
    global input_focused
    input_focused = False


def hide_text_after_delay(tag: str, sleep_time: int) -> None:
    time.sleep(sleep_time)
    dpg.hide_item(tag)


def __update_dropdown(tag: str) -> None:
    if tag == "project_update_project_name_dropdown":
        customer_name = dpg.get_value("project_update_customer_name_dropdown")
        projects = (
            df[df["customer_name"] == customer_name]["project_name"].unique().tolist()
        )
        dpg.configure_item(tag, items=projects)
    elif tag == "project_delete_project_name_dropdown":
        customer_name = dpg.get_value("project_delete_customer_name_dropdown")
        projects = (
            df[df["customer_name"] == customer_name]["project_name"].unique().tolist()
        )
        dpg.configure_item(tag, items=projects)


def __autoset_query_window(table_name: str) -> None:
    sql_input = f"select * from {dpg.get_item_label(table_name)}"
    dpg.set_value("query_input", sql_input)


def on_date_selected(sender, app_data):
    selected = f"{app_data['year'] + 1900}-{app_data['month'] + 1:02d}-{app_data['month_day']:02d}"
    print(f"Date selected: {selected}")


###
# Button Functions
###
def time_span_callback(sender, app_data):
    print(f"Selected Time Span: {dpg.get_value('time_span_group')}")


def data_type_callback(sender, app_data):
    print(f"Selected Data Type: {dpg.get_value('data_type_group')}")


def project_button_callback(sender, app_data, user_data):
    customer_id, project_id = user_data

    if app_data:
        print(
            f"Clicked and enabled - Customer ID: {customer_id}, Project ID: {project_id}"
        )
    else:
        show_project_popup(sender, app_data, customer_id, project_id)


def show_project_popup(sender, app_data, customer_id, project_id):
    window_tag = f"popup_{customer_id}_{project_id}"

    if not dpg.does_item_exist(window_tag):
        with dpg.window(
            tag=window_tag,
            modal=True,
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_close=True,
            width=300,
            height=150,
        ):
            dpg.add_text(f"Work Comments")
            dpg.add_input_int(
                label="Git-ID (Opt.)", tag=f"git_id_{customer_id}_{project_id}"
            )
            dpg.add_input_text(
                multiline=True,
                label="Comment",
                tag=f"comment_{customer_id}_{project_id}",
                height=60,
            )

            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Save",
                    callback=lambda: save_popup_data(
                        customer_id, project_id, window_tag
                    ),
                )
                dpg.add_button(
                    label="Cancel",
                    callback=lambda: cancel_popup_action(
                        sender, app_data, customer_id, project_id, window_tag
                    ),
                )
    else:
        dpg.configure_item(window_tag, show=True)


def save_popup_data(customer_id, project_id, window_tag):
    git_id = dpg.get_value(f"git_id_{customer_id}_{project_id}")
    comment = dpg.get_value(f"comment_{customer_id}_{project_id}")
    print(f"Saved for Customer ID: {customer_id}, Project ID: {project_id}")
    print(f"Git-ID: {git_id}, Comment: {comment}")
    dpg.delete_item(window_tag)


def cancel_popup_action(sender, app_data, customer_id, project_id, window_tag):
    print(f"Cancel action for Customer ID: {customer_id}, Project ID: {project_id}")
    dpg.set_value(sender, not app_data)
    dpg.delete_item(window_tag)


def handle_query_input():
    if input_focused:
        query_text = dpg.get_value("query_input")
        print(f"Query Entered: {query_text}")


###
# Generic User Input
###
def add_save_button(function_name, tag_name: str, label: str):
    dpg.add_spacer(width=10)
    with dpg.group(horizontal=True):
        dpg.add_button(label=label, callback=function_name)
        dpg.add_loading_indicator(
            tag=f"{tag_name}_save_spinner", style=1, radius=1.25, show=False
        )
        dpg.add_text("", tag=f"{tag_name}_error_label", show=False, color=WARNING_RED)
    dpg.add_spacer(width=10)


def __hide_text_after_seconds(
    tag: str, text: str, delay: int, error: bool = True
) -> None:
    dpg.set_value(tag, text)
    if error:
        dpg.configure_item(tag, color=WARNING_RED)
    else:
        dpg.configure_item(tag, color=WARNING_GREEN)
    dpg.show_item(tag)
    threading.Thread(
        target=hide_text_after_delay, args=(tag, delay), daemon=True
    ).start()


def set_start_date():  ## TODO make this more generic if needed to be reused!
    date_struct = dpg.get_value("customer_add_start_date_picker")
    date_str = __format_date_struct(date_struct)
    dpg.set_value("customer_add_start_date_label", date_str)
    dpg.hide_item("start_button_popup")


###
# User Input
###
def add_customer_data(sender, app_data) -> None:
    customer_name = dpg.get_value("customer_add_name_input")
    if customer_name == "":
        __hide_text_after_seconds(
            "customer_add_error_label", "Cannot have blank customer name!", 3
        )
        return
    start_date = dpg.get_value("customer_add_start_date_label")
    if start_date == "":
        __hide_text_after_seconds(
            "customer_add_error_label", "Cannot have blank start date!", 3
        )
        return

    amount = dpg.get_value("customer_add_wage_input")

    if __is_valid_date(start_date):
        dpg.show_item("customer_add_save_spinner")
        print(
            f"Customer Name: {customer_name}, Start Date: {start_date}, Amount: {amount}"
        )
        __hide_text_after_seconds(
            "customer_add_error_label", "Adding customer to DB!", 3, error=False
        )
        time.sleep(3)
        dpg.hide_item("customer_add_save_spinner")
    else:
        __hide_text_after_seconds("customer_add_error_label", "Invalid start date!", 3)
        return


def update_customer_data(sender, app_data) -> None:
    customer_name = dpg.get_value("customer_update_name_dropdown")
    if customer_name == "":
        __hide_text_after_seconds(
            "customer_update_error_label", "No customer selected!", 3
        )
        return
    new_customer_name = dpg.get_value("customer_update_customer_name_input")
    if new_customer_name == "":
        __hide_text_after_seconds(
            "customer_update_error_label", "Cannot have blank customer name!", 3
        )
        return
    customer_wage = dpg.get_value("customer_update_wage_input")
    __hide_text_after_seconds(
        "customer_update_error_label", "Updating customer in DB!", 3, error=False
    )

    print(
        f"Customer: {customer_name}, New Values: {new_customer_name}, {customer_wage}"
    )


def delete_customer_data(sender, app_data) -> None:
    customer_name = dpg.get_value("customer_delete_name_dropdown")
    if customer_name == "":
        __hide_text_after_seconds(
            "customer_delete_error_label", "No customer selected!", 3
        )
        return
    __hide_text_after_seconds(
        "customer_delete_error_label", "Disabling customer in DB!", 3, error=False
    )

    print(f"Removing customer: {customer_name}")


def add_project_data(sender, app_data) -> None:
    customer_name = dpg.get_value("project_add_customer_name_input")
    if customer_name == "":
        __hide_text_after_seconds("project_add_error_label", "No customer selected!", 3)
        return
    project_name = dpg.get_value("project_add_name_input")
    if project_name == "":
        __hide_text_after_seconds(
            "project_add_error_label", "Cannot have blank project name!", 3
        )
        return

    dpg.show_item("project_add_save_spinner")
    print(f"Customer Name: {customer_name}, Project Name: {project_name}")
    __hide_text_after_seconds(
        "project_add_error_label", "Adding project to DB!", 3, error=False
    )
    time.sleep(3)
    dpg.hide_item("project_add_save_spinner")


def update_project_data(sender, app_data) -> None:
    customer_name = dpg.get_value("project_update_customer_name_dropdown")
    if customer_name == "":
        __hide_text_after_seconds(
            "project_update_error_label", "No customer selected!", 3
        )
        return
    project_name = dpg.get_value("project_update_project_name_dropdown")
    if customer_name == "":
        __hide_text_after_seconds(
            "project_update_error_label", "No project selected!", 3
        )
        return
    new_project_name = dpg.get_value("project_update_name_input")
    if new_project_name == "":
        __hide_text_after_seconds(
            "project_update_error_label", "Cannot have blank project name!", 3
        )
        return
    print(
        f"Customer: {customer_name}, Project: {project_name} is renamed: {new_project_name}"
    )
    __hide_text_after_seconds(
        "project_update_error_label", "Updating project in DB!", 3, error=False
    )


def delete_project_data(sender, app_data) -> None:
    customer_name = dpg.get_value("project_delete_customer_name_dropdown")
    if customer_name == "":
        __hide_text_after_seconds(
            "project_delete_error_label", "No customer selected!", 3
        )
        return
    project_name = dpg.get_value("project_delete_project_name_dropdown")
    if project_name == "":
        __hide_text_after_seconds(
            "project_delete_error_label", "No project selected!", 3
        )
        return

    print(f"Removing customer: {customer_name}, project: {project_name}")
    __hide_text_after_seconds(
        "project_delete_error_label", "Disabling project in DB!", 3, error=False
    )


###
# UI
###
with dpg.window(label="Work Timer v2", width=500, height=600):
    ## Input
    with dpg.collapsing_header(label="Input", default_open=False):
        with dpg.collapsing_header(
            label="Customers", default_open=False, indent=INDENT_1
        ):
            with dpg.collapsing_header(
                label="Add Customer", default_open=False, indent=INDENT_2
            ):
                dpg.add_input_text(label="Customer Name", tag="customer_add_name_input")
                dpg.add_input_int(label="Wage", tag="customer_add_wage_input")

                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="customer_add_start_date_label")
                    dpg.add_image_button(
                        texture_tag=icon_calendar,
                        tag="customer_add_start_date_button",
                        width=14,
                        height=14,
                    )
                    dpg.add_text("Start Date")

                with dpg.popup(
                    parent="customer_add_start_date_button",
                    mousebutton=dpg.mvMouseButton_Left,
                    modal=True,
                    tag="start_button_popup",
                ):
                    today_struct = __get_current_date_struct()
                    dpg.add_date_picker(
                        label="Start Date",
                        tag="customer_add_start_date_picker",
                        default_value=today_struct,
                    )
                    dpg.add_button(label="Done", callback=set_start_date)

                add_save_button(add_customer_data, "customer_add", "Save")

            with dpg.collapsing_header(
                label="Update Customer", default_open=False, indent=INDENT_2
            ):
                customers = df["customer_name"].unique().tolist()
                df_first_row = df.iloc[0]
                first_customer = df_first_row["customer_name"]
                wage = df_first_row["wage"]

                dpg.add_combo(
                    customers,
                    default_value=first_customer,
                    width=COMBO_WIDTH,
                    label="Customer Name",
                    tag="customer_update_name_dropdown",
                )
                dpg.add_input_text(
                    label="New Customer Name",
                    default_value=first_customer,
                    tag="customer_update_customer_name_input",
                )
                dpg.add_input_int(
                    label="Wage",
                    default_value=int(wage),
                    tag="customer_update_wage_input",
                )
                add_save_button(update_customer_data, "customer_update", "Update")

            with dpg.collapsing_header(
                label="Remove Customer", default_open=False, indent=INDENT_2
            ):
                dpg.add_combo(
                    customers,
                    default_value="",
                    width=COMBO_WIDTH,
                    label="Customer Name",
                    tag="customer_delete_name_dropdown",
                )
                add_save_button(delete_customer_data, "customer_delete", "Remove")

        with dpg.collapsing_header(
            label="Project", default_open=False, indent=INDENT_1
        ):
            with dpg.collapsing_header(
                label="Add Project", default_open=False, indent=INDENT_2
            ):
                customers = df["customer_name"].unique().tolist()
                dpg.add_combo(
                    customers,
                    width=COMBO_WIDTH,
                    label="Customer Name",
                    tag="project_add_customer_name_dropdown",
                )
                dpg.add_input_text(label="Project Name", tag="project_add_name_input")
                add_save_button(add_project_data, "project_add", "Save")

            with dpg.collapsing_header(
                label="Update Project", default_open=False, indent=INDENT_2
            ):
                customers = df["customer_name"].unique().tolist()
                dpg.add_combo(
                    customers,
                    width=COMBO_WIDTH,
                    label="Customer Name",
                    tag="project_update_customer_name_dropdown",
                    callback=lambda: __update_dropdown(
                        tag="project_update_project_name_dropdown"
                    ),
                )
                dpg.add_combo(
                    [],
                    width=COMBO_WIDTH,
                    label="Project Name",
                    tag="project_update_project_name_dropdown",
                )
                dpg.add_input_text(
                    label="New Project Name", tag="project_update_name_input"
                )

                add_save_button(update_project_data, "project_update", "Update")

            with dpg.collapsing_header(
                label="Remove Project", default_open=False, indent=INDENT_2
            ):
                customers = df["customer_name"].unique().tolist()
                dpg.add_combo(
                    customers,
                    width=COMBO_WIDTH,
                    label="Customer Name",
                    tag="project_delete_customer_name_dropdown",
                    callback=lambda: __update_dropdown(
                        tag="project_delete_project_name_dropdown"
                    ),
                )
                dpg.add_combo(
                    [],
                    width=COMBO_WIDTH,
                    label="Project Name",
                    tag="project_delete_project_name_dropdown",
                )

                add_save_button(delete_project_data, "project_delete", "Remove")

    ## Settings
    with dpg.collapsing_header(label="Settings", default_open=True):
        with dpg.group(horizontal=True):  # Time Span
            with dpg.group():
                dpg.add_text("Select Time Span:")
                time_span_options = ["Day", "Week", "Month", "Year", "All-Time"]
                dpg.add_radio_button(
                    label="Time Span",
                    items=time_span_options,
                    tag="time_span_group",
                    callback=time_span_callback,
                )

            with dpg.group():  # Data Type
                dpg.add_text("Select Data Type:")
                data_type_options = ["Time", "Cost"]
                dpg.add_radio_button(
                    label="Data Type",
                    items=data_type_options,
                    tag="data_type_group",
                    callback=data_type_callback,
                )

            with dpg.group():  # Date Selection
                today_struct = __get_current_date_struct()
                dpg.add_text("Select Date:")
                dpg.add_date_picker(
                    default_value=today_struct, callback=on_date_selected
                )

    # "Queries" Section
    with dpg.collapsing_header(label="Queries", default_open=False):
        with dpg.group():
            available_tables = ["times", "customers", "projects", "bonus", "dates"]
            with dpg.group(horizontal=True):
                dpg.add_text("Available tables:")
                for table in available_tables:
                    dpg.add_button(
                        label=table,
                        callback=lambda t=str(table): __autoset_query_window(t),
                    )

            dpg.add_spacer(width=10)
            dpg.add_text("Enter Query:")
            sql_input = "select * from times"
            dpg.add_input_text(
                multiline=True,
                width=480,
                height=100,
                tag="query_input",
                default_value=sql_input,
            )

            # For f5 runs so only work when query is selected
            with dpg.item_handler_registry(tag="query_input_handler") as handler:
                dpg.add_item_activated_handler(
                    callback=on_input_focus
                )  # Triggered when user clicks into it
                dpg.add_item_deactivated_after_edit_handler(
                    callback=on_input_unfocus
                )  # Triggered when they click out

            dpg.bind_item_handler_registry("query_input", "query_input_handler")

        # Box for displaying tabular data
        with dpg.group():
            dpg.add_text("Tabular Data:")

            with dpg.table(tag="data_table", resizable=True, width=480):
                # Define columns
                dpg.add_table_column(label="Customer ID")
                dpg.add_table_column(label="Customer Name")
                dpg.add_table_column(label="Project ID")
                dpg.add_table_column(label="Project Name")

                # Add data from the DataFrame
                # for index, row in df.iterrows():
                #     # Add a row before adding cells
                #     with dpg.table_row():
                #         # Add each item in the row as a table cell, ensuring conversion to string
                #         dpg.add_table_cell(content=str(row["customer_id"]))
                #         dpg.add_table_cell(content=row["customer_name"])
                #         dpg.add_table_cell(content=str(row["project_id"]))
                #         dpg.add_table_cell(content=row["project_name"])

    with dpg.handler_registry():
        dpg.add_key_press_handler(key=dpg.mvKey_F5, callback=handle_query_input)

    with dpg.collapsing_header(label="Customers", default_open=True):
        # Customer and project UI
        for customer_id in df["customer_id"].unique():
            customer_name = df.loc[
                df["customer_id"] == customer_id, "customer_name"
            ].iloc[0]
            with dpg.collapsing_header(
                label=customer_name, default_open=True, indent=INDENT_2
            ):
                total_text = f"Total: 0 h 0 min"
                dpg.add_text(total_text, tag=f"total_{customer_id}")
                for _, row in df[df["customer_id"] == customer_id].iterrows():
                    project_id = row["project_id"]
                    project_name = row["project_name"]
                    initial_state = row["initial_state"]
                    initial_text = row["initial_text"]

                    with dpg.group(horizontal=True):
                        dpg.add_checkbox(
                            label=f"{project_name:<15}",
                            callback=project_button_callback,
                            user_data=(customer_id, project_id),
                            default_value=initial_state,
                        )
                        dpg.add_text(
                            initial_text, tag=f"time_{customer_id}_{project_id}"
                        )


dpg.create_viewport(
    title="Work Timer v2",
    width=500,
    height=650,
    small_icon="favicon.ico",
    large_icon="favicon.ico",
)
dpg.setup_dearpygui()
dpg.show_viewport()

update_total_time(0, "Total: 3 h 10 min")

dpg.start_dearpygui()
dpg.destroy_context()
