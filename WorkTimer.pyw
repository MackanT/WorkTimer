import dearpygui.dearpygui as dpg
from datetime import datetime, timedelta
import pandas as pd
import time
import queue
import threading

import os
import json

from database import Database
from devops import DevOpsClient

###
# Constants
###
COMBO_WIDTH = 325
INDENT_1 = 15
INDENT_2 = 10

WARNING_RED = [255, 99, 71]
WARNING_GREEN = [34, 139, 34]

COMMIT = True
INIT = True

QUERY_WIDTH = 1280
WIDTH = 500
HEIGHT = 600

TIME_ID = 0  # 0 = Day, 1 = Week, 2 = Month, 3 = Year, 4 = All-Time
TYPE_ID = 0  # 0 = Time, 1 = Bonus Wage
SELECTED_DATE = datetime.now().strftime("%Y-%m-%d")
CURRENT_DATE = datetime.now().date()

###
# SQL-Backend logic
###
db_file = "data_dpg.db"

db = Database(db_file)
db.initialize_db()


###
# DepOps Connection
###
do_con = {}
df_do = db.fetch_query(
    "select distinct customer_name, pat_token, org_url from customers where pat_token is not null and org_url is not null"
)
for _, row in df_do.iterrows():
    org_url = f"https://dev.azure.com/{row['org_url']}"
    do_con[row["customer_name"]] = DevOpsClient(
        row["pat_token"], org_url
    )  # TODO add fix for missing PAT token
    do_con[row["customer_name"]].connect()
    db.pre_run_log.append(
        f"DevOps connection established to {row['customer_name']} for organization {row['org_url']}"
    )

# personal_access_token = "2Ae4xSjyf1m62hWmywoDxJIDcd4f3fzPSlNqzGomnlRKKTIXZFOrJQQJ99BEACAAAAABrcj0AAASAZDO33L0"
# organization_url = "https://dev.azure.com/rowico"
# do = DevOpsClient(personal_access_token, organization_url)
# do.connect()

dpg.create_context()

## Image Input
width, height, channels, data = dpg.load_image("graphics\\icon_calendar.png")
with dpg.texture_registry():
    icon_calendar = dpg.add_static_texture(width, height, data)

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


def __is_valid_date(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def populate_pre_log():
    for line in db.pre_run_log:
        __log_message(line, type="INFO")


def __log_message(message: str, type: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_log = dpg.get_value("log_box")
    new_log = (
        f"{timestamp} [{type}] - {message}\n{current_log}"
        if current_log
        else f"{timestamp} [{type}] - {message}"
    )
    dpg.set_value("log_box", new_log)


def _get_value_from_df(df: pd.DataFrame, data_type: str = "str"):
    if isinstance(df, pd.DataFrame):
        val = df.iloc[0, 0]
    elif isinstance(df, pd.Series):
        val = df.iloc[0]
    else:
        val = df

    if data_type == "str":
        return val if val is not None else ""
    elif data_type == "int":
        return int(val) if val is not None else 0
    elif data_type == "float":
        return float(val) if val is not None else 0.0
    else:
        raise ValueError("Invalid data type specified.")


###
# UI Functions
###
def on_input_focus(sender, app_data) -> None:
    global input_focused
    input_focused = True


def on_input_unfocus(sender, app_data) -> None:
    global input_focused
    input_focused = False


def hide_text_after_delay(tag: str, sleep_time: int) -> None:
    time.sleep(sleep_time)
    dpg.hide_item(tag)


def __update_dropdown(tag: str, c_name: str = None) -> None:
    if tag == "customer_dropdown":
        r_queue = queue.Queue()
        db.queue_task("get_customer_names", {}, response=r_queue)
        customers = r_queue.get()
        dpg.configure_item("customer_update_name_dropdown", items=customers)
        dpg.configure_item("customer_delete_name_dropdown", items=customers)
        dpg.configure_item("project_add_customer_name_dropdown", items=customers)

        db.queue_task("get_active_customers", {}, response=r_queue)
        customers = r_queue.get()
        dpg.configure_item("project_update_customer_name_dropdown", items=customers)
        dpg.configure_item("project_delete_customer_name_dropdown", items=customers)

    elif tag == "project_update_project_name_dropdown":
        if INIT:  # Ensure no dead-lock during setup
            return

        customer_name = dpg.get_value("project_update_customer_name_dropdown")

        r_queue = queue.Queue()
        db.queue_task(
            "get_project_names", {"customer_name": customer_name}, response=r_queue
        )
        projects = r_queue.get()
        dpg.configure_item(tag, items=projects)
    elif tag == "project_delete_project_name_dropdown":
        if INIT:  # Ensure no dead-lock during setup
            return

        customer_name = dpg.get_value("project_delete_customer_name_dropdown")
        r_queue = queue.Queue()
        db.queue_task(
            "get_project_names", {"customer_name": customer_name}, response=r_queue
        )
        projects = r_queue.get()
        dpg.configure_item(tag, items=projects)


def __update_text_input(tag: str):
    if tag == "customer_update_name_dropdown":
        cur_val = dpg.get_value(tag)
        dpg.set_value("customer_update_customer_name_input", cur_val)

        r_queue = queue.Queue()
        db.queue_task("get_wage", {"customer_name": cur_val}, response=r_queue)
        new_wage = r_queue.get()

        dpg.set_value("customer_update_wage_input", new_wage)
    elif tag == "project_update_project_name_dropdown":
        cur_p_name = dpg.get_value(tag)
        cur_c_name = dpg.get_value("project_update_customer_name_dropdown")
        dpg.set_value("project_update_name_input", cur_p_name)

        r_queue = queue.Queue()
        query = f"""select git_id from projects p
                    left join customers c on c.customer_id = p.customer_id and c.is_current = 1
                    where p.project_name = '{cur_p_name}'
                    and c.customer_name = '{cur_c_name}'
                    and p.is_current = 1
                    limit 1"""
        db.queue_task("get_df", {"query": query}, response=r_queue)
        git_id = _get_value_from_df(r_queue.get(), data_type="int")
        dpg.set_value("project_update_git_input", git_id)


def __autoset_query_window(table_name: str) -> None:
    sql_input = f"select * from {dpg.get_item_label(table_name)}"
    dpg.set_value("query_input", sql_input)


def on_date_selected(sender, app_data) -> None:
    global SELECTED_DATE
    SELECTED_DATE = f"{app_data['year'] + 1900}-{app_data['month'] + 1:02d}-{app_data['month_day']:02d}"

    run_update_ui_task()
    __log_message(f"Date selected: {SELECTED_DATE}", type="INFO")


def __get_user_input() -> tuple[int, int, str]:
    global TIME_ID, TYPE_ID, SELECTED_DATE

    d_queue = queue.Queue()
    db.queue_task("get_df", {"query": "select * from dates"}, response=d_queue)
    dates = d_queue.get()

    sel_date = pd.to_datetime(SELECTED_DATE)

    start_date = end_date = sel_date

    if TIME_ID == 4:
        start_date = int(dates["date"].min().replace("-", ""))
        end_date = int(dates["date"].max().replace("-", ""))
    else:
        if TIME_ID == 1:
            start_date = sel_date - timedelta(days=sel_date.weekday())
            end_date = start_date + timedelta(days=6)
        elif TIME_ID == 2:
            start_date = sel_date.replace(day=1)
            next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
            end_date = next_month - timedelta(days=1)
        elif TIME_ID == 3:
            start_date = sel_date.replace(month=1, day=1)
            end_date = sel_date.replace(month=12, day=31)

        start_date = start_date.strftime("%Y%m%d")
        end_date = end_date.strftime("%Y%m%d")

    if TYPE_ID == 0:
        sel_type = "total_time"
    elif TYPE_ID == 1:
        sel_type = "cost"

    return start_date, end_date, sel_type


# Global variable to store the header order
header_order = []


def render_customer_project_ui():
    global header_order

    start_date, end_date, sel_type = __get_user_input()

    # Fetch the default order of customer IDs from the database
    r_queue = queue.Queue()
    db.queue_task(
        "get_customer_ui_list",
        {"start_date": start_date, "end_date": end_date, "data_type": sel_type},
        response=r_queue,
    )
    df = r_queue.get()

    dpg.delete_item("customer_ui_section", children_only=True)

    __update_dropdown("customer_dropdown")

    cid = 0
    cids = df["customer_id"].unique().tolist()
    for customer_id in cids:
        customer_name = df.loc[df["customer_id"] == customer_id, "customer_name"].iloc[
            0
        ]

        # One header per customer inside the "Customers" section
        header_id = dpg.add_collapsing_header(
            label=customer_name,
            default_open=True,
            indent=10,
            parent="customer_ui_section",
            tag=f"header_{customer_id}",
        )

        # Add "Move Up" and "Move Down" buttons
        with dpg.group(horizontal=True, parent=header_id):
            dpg.add_text("", tag=f"total_{customer_id}")
            dpg.add_spacer(width=WIDTH / 2 - INDENT_1 - 5)
            if cid == 0:
                dpg.add_spacer(width=55)
            if cid != 0:
                dpg.add_button(
                    label="Move Up",  # ↑
                    callback=move_header_up,
                    user_data=customer_id,
                )
            if cid != len(cids) - 1:
                dpg.add_button(
                    label="Move Down",
                    callback=move_header_down,
                    user_data=customer_id,
                )
        cid += 1

        db_queue = queue.Queue()
        for _, row in df[df["customer_id"] == customer_id].iterrows():
            project_id = row["project_id"]
            project_name = row["project_name"]

            sql_query = f"select * from time where customer_id = {customer_id} and project_id = {project_id} and end_time is null"
            db.queue_task(
                "get_df",
                {"query": sql_query, "meta_data": "render_customer_project_ui"},
                response=db_queue,
            )
            counts = db_queue.get()
            initial_state = True if len(counts) > 0 else False

            group_id = dpg.add_group(horizontal=True, parent=header_id)

            dpg.add_checkbox(
                label=f"{project_name:<44}",
                callback=project_button_callback,
                user_data=(customer_id, project_id, customer_name),
                default_value=initial_state,
                parent=group_id,
            )

            dpg.add_text("", tag=f"time_{customer_id}_{project_id}", parent=group_id)
        # dpg.add_spacer(height=10, parent="customer_ui_section")

    # Save the current order of headers
    # save_header_order()

    run_update_ui_task()


def _get_header_df() -> pd.DataFrame:
    query_text = "select customer_id, customer_name, sort_order from customers"
    r_queue = queue.Queue()
    db.queue_task("run_query", {"query": query_text}, response=r_queue)
    df = r_queue.get()
    return df


def move_header_up(sender, app_data, customer_id: int) -> None:
    """Move the header up in the custom order."""

    df = _get_header_df()

    cur_order = df[df["customer_id"] == customer_id]["sort_order"].iloc[0]
    min_order = df["sort_order"].min()

    if cur_order == min_order:
        # Already top level
        return

    nex_rows = df[df["sort_order"] == cur_order - 1]
    nex_order = nex_rows["sort_order"].iloc[0]
    nex_ids = nex_rows["customer_id"].unique().tolist()

    id_list = ",".join(str(x) for x in nex_ids)
    q1 = f"update customers set sort_order = {nex_order} where customer_id = {customer_id}"
    q2 = f"update customers set sort_order = {cur_order} where customer_id in ({id_list})"

    db.queue_task("run_query", {"query": q1})
    db.queue_task("run_query", {"query": q2})

    render_customer_project_ui()


def move_header_down(sender, app_data, customer_id: int) -> None:
    """Move the header down in the custom order."""

    df = _get_header_df()

    cur_order = df[df["customer_id"] == customer_id]["sort_order"].iloc[0]
    max_order = df["sort_order"].max()

    if cur_order == max_order:
        # Already top level
        return

    nex_rows = df[df["sort_order"] == cur_order + 1]
    nex_order = nex_rows["sort_order"].iloc[0]
    nex_ids = nex_rows["customer_id"].unique().tolist()

    id_list = ",".join(str(x) for x in nex_ids)
    q1 = f"update customers set sort_order = {nex_order} where customer_id = {customer_id}"
    q2 = f"update customers set sort_order = {cur_order} where customer_id in ({id_list})"

    db.queue_task("run_query", {"query": q1})
    db.queue_task("run_query", {"query": q2})

    render_customer_project_ui()


###
# Button Functions
###
def time_span_callback(sender, app_data):
    global TIME_ID
    pressed_val = dpg.get_value("time_span_group")

    if pressed_val == "Day":
        TIME_ID = 0
    elif pressed_val == "Week":
        TIME_ID = 1
    elif pressed_val == "Month":
        TIME_ID = 2
    elif pressed_val == "Year":
        TIME_ID = 3
    elif pressed_val == "All-Time":
        TIME_ID = 4
    run_update_ui_task()


def data_type_callback(sender, app_data):
    global TYPE_ID

    pressed_val = dpg.get_value("data_type_group")
    if pressed_val == "Time":
        TYPE_ID = 0
    elif pressed_val == "Bonus Wage":
        TYPE_ID = 1
    run_update_ui_task()


def project_button_callback(sender, app_data, user_data):
    customer_id, project_id, customer_name = user_data

    if app_data:
        db.insert_time_row(int(customer_id), int(project_id))
    else:
        show_project_popup(sender, app_data, customer_id, project_id, customer_name)

    run_update_ui_task()


def show_project_popup(
    sender, app_data, customer_id: int, project_id: int, customer_name: str
):
    window_tag = f"popup_{customer_id}_{project_id}"

    if not dpg.does_item_exist(window_tag):
        with dpg.window(
            tag=window_tag,
            modal=True,
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_close=True,
            width=WIDTH / 2,
            height=HEIGHT / 3,
        ):
            git_queue = queue.Queue()
            query = f"select git_id from projects where project_id = {project_id} and customer_id = {customer_id} and is_current = 1"
            db.queue_task("get_df", {"query": query}, response=git_queue)
            df = git_queue.get()
            git_id = _get_value_from_df(df, data_type="int")

            dpg.add_text("Work Comments")
            dpg.add_input_int(
                label="Git-ID (Opt.)",
                tag=f"git_id_{customer_id}_{project_id}",
                default_value=git_id,
            )
            def_val = True if git_id != 0 else False
            dpg.add_checkbox(
                label="Store to DevOps",
                tag=f"devops_{customer_id}_{project_id}",
                default_value=def_val,  # Checked by default
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
                        customer_id, project_id, window_tag, customer_name
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


def save_popup_data(customer_id: int, project_id: int, window_tag, customer_name: str):
    git_id = dpg.get_value(f"git_id_{customer_id}_{project_id}")
    comment = dpg.get_value(f"comment_{customer_id}_{project_id}")
    store_to_devops = dpg.get_value(f"devops_{customer_id}_{project_id}")

    db.insert_time_row(int(customer_id), int(project_id), git_id, comment)

    if store_to_devops:
        if git_id != 0 and comment != "":
            status = do_con[customer_name].add_comment_to_work_item(git_id, comment)
            if status:
                print("Error:", status)
                show_error_popup(status)

    dpg.delete_item(window_tag)


def cancel_popup_action(sender, app_data, customer_id, project_id, window_tag):
    dpg.set_value(sender, not app_data)
    dpg.delete_item(window_tag)


def show_error_popup(error_message: str = None) -> None:
    if not dpg.does_item_exist("error_popup"):
        with dpg.popup(parent="query_output_group", tag="error_popup", modal=True):
            dpg.add_text(error_message, wrap=400, tag="error_text")
            dpg.add_button(label="OK", callback=lambda: dpg.hide_item("error_popup"))
            dpg.configure_item("error_popup", show=True)
    else:
        dpg.configure_item("error_popup", show=True)
        dpg.set_value("error_text", error_message)


def open_query_popup():
    dpg.set_viewport_width(QUERY_WIDTH + 20)
    if dpg.does_item_exist("query_popup_window"):
        dpg.delete_item("query_popup_window")
    with dpg.window(
        label="Query Results",
        tag="query_popup_window",
        width=QUERY_WIDTH,
        height=600,
        modal=True,
        no_close=True,
    ):
        dpg.add_button(
            label="Close",
            callback=lambda: (
                dpg.set_viewport_width(WIDTH + 15),  # Restore original width
                dpg.set_viewport_height(
                    HEIGHT + 50
                ),  # Restore original height if changed
                dpg.delete_item("query_popup_window"),
            ),
        )

        with dpg.group():
            available_tables = ["time", "customers", "projects", "bonus"]
            with dpg.group(horizontal=True):
                dpg.add_text("Available tables:")
                for table in available_tables:
                    dpg.add_button(
                        label=table,
                        callback=lambda t=str(table): __autoset_query_window(
                            table_id=t
                        ),
                    )

            dpg.add_spacer(width=10)
            dpg.add_text("Enter Query:")

            sql_input = "select * from time"
            dpg.add_input_text(
                multiline=True,
                width=QUERY_WIDTH - 30,
                height=HEIGHT / 6,
                tag="query_input",
                default_value=sql_input,
            )
            __autoset_query_window(table_name="time")

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
        # with dpg.group(tag="query_output_group"):
        dpg.add_text("Tabular Data:")

        handle_query_input()

    with dpg.handler_registry():
        dpg.add_key_press_handler(key=dpg.mvKey_F5, callback=handle_query_input)


def handle_query_input():
    # Always try to get the query from the popup input if it exists
    if dpg.does_item_exist("query_input"):
        query_text = dpg.get_value("query_input")
        r_queue = queue.Queue()
        db.queue_task("run_query", {"query": query_text}, response=r_queue)
        df = r_queue.get()

        if isinstance(df, list) and len(df) == 0:
            show_error_popup("Command completed successfully!")
            return
        elif isinstance(df, pd.errors.DatabaseError) or len(df) == 0:
            show_error_popup(df)
            return
        elif df is None or not isinstance(df, pd.DataFrame) or df.empty:
            print("Query Error: No data returned! Evaluate and find when we get here!")
            return

        # Remove previous table if it exists
        if dpg.does_item_exist("query_table"):
            dpg.delete_item("query_table")

        # Add new table to the popup
        with dpg.table(
            parent="query_popup_window",
            tag="query_table",
            header_row=True,
            policy=dpg.mvTable_SizingStretchProp,
            scrollY=True,
            scrollX=True,
            clipper=True,
            resizable=True,
            reorderable=True,
            width=QUERY_WIDTH,
        ):
            char_width = 8
            min_width = 60
            max_width = 300
            for col in df.columns:
                max_len = max([len(str(x)) for x in df[col].values] + [len(str(col))])
                col_width = max(min_width, max_len * char_width)
                col_width = min(col_width, max_width)
                dpg.add_table_column(label=col, init_width_or_weight=col_width)
            arr = df.to_numpy()
            for i in range(df.shape[0]):
                with dpg.table_row():
                    for j in range(df.shape[1]):
                        dpg.add_text(str(arr[i, j]))


###
# Generic User Input
###
def add_save_button(function_name, tag_name: str, label: str):
    dpg.add_spacer(width=10)
    with dpg.group(horizontal=True):
        dpg.add_button(label=label, callback=function_name)
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


def set_start_date(
    item_tag: str,
) -> None:
    date_struct = dpg.get_value(f"{item_tag}_start_date_picker")
    date_str = __format_date_struct(date_struct)
    dpg.set_value(f"{item_tag}_start_date_input", date_str)
    dpg.hide_item(f"{item_tag}_start_button_popup")


###
# User Input
###
def __post_user_input() -> None:
    # Add Customer
    dpg.set_value("customer_add_name_input", "")
    dpg.set_value("customer_add_start_date_input", "")
    dpg.set_value("customer_add_wage_input", 0)
    # Update Customer
    dpg.set_value("customer_update_name_dropdown", "")
    dpg.set_value("customer_update_customer_name_input", "")
    dpg.set_value("customer_update_wage_input", 0)
    # Remove Customer
    dpg.set_value("customer_delete_name_dropdown", "")
    # Add Project
    dpg.set_value("project_add_customer_name_dropdown", "")
    dpg.set_value("project_add_name_input", "")
    dpg.set_value("project_add_git_input", 0)
    # Update Project
    dpg.set_value("project_update_customer_name_dropdown", "")
    dpg.set_value("project_update_project_name_dropdown", "")
    dpg.set_value("project_update_name_input", "")
    dpg.set_value("project_update_git_input", 0)
    # Remove Project
    dpg.set_value("project_delete_customer_name_dropdown", "")
    dpg.set_value("project_delete_project_name_dropdown", "")
    # Add Bonus
    dpg.set_value("bonus_add_amount_input", 0.0)
    dpg.set_value("bonus_add_start_date_input", "")

    render_customer_project_ui()


def add_customer_data(sender, app_data) -> None:
    customer_name = dpg.get_value("customer_add_name_input")
    if customer_name == "":
        __hide_text_after_seconds(
            "customer_add_error_label", "Cannot have blank customer name!", 3
        )
        return
    start_date = dpg.get_value("customer_add_start_date_input")
    if start_date == "":
        __hide_text_after_seconds(
            "customer_add_error_label", "Cannot have blank start date!", 3
        )
        return

    amount = dpg.get_value("customer_add_wage_input")

    ## Case Success:
    if __is_valid_date(start_date):
        __hide_text_after_seconds(
            "customer_add_error_label", "Adding customer to DB!", 3, error=False
        )
        db.queue_task(
            "insert_customer",
            {"customer_name": customer_name, "start_date": start_date, "wage": amount},
        )
        __update_dropdown("customer_dropdown")
        __post_user_input()
        __log_message(
            f"Customer {customer_name} added to DB with start date {start_date} and wage {amount}",
            type="INFO",
        )

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

    ## Success Case:
    customer_wage = dpg.get_value("customer_update_wage_input")
    __hide_text_after_seconds(
        "customer_update_error_label", "Updating customer in DB!", 3, error=False
    )
    db.queue_task(
        "update_customer",
        {
            "customer_name": customer_name,
            "new_customer_name": new_customer_name,
            "wage": customer_wage,
        },
    )
    __update_dropdown("customer_dropdown")
    __post_user_input()
    __log_message(
        f"Customer {customer_name} in DB renamed to {new_customer_name} with wage {customer_wage}",
        type="INFO",
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
    db.queue_task("remove_customer", {"customer_name": customer_name})
    __update_dropdown("customer_dropdown")
    __post_user_input()
    __log_message(
        f"Customer {customer_name} disabled in the DB",
        type="INFO",
    )

    render_customer_project_ui()


def add_project_data(sender, app_data) -> None:
    customer_name = dpg.get_value("project_add_customer_name_dropdown")
    if customer_name == "":
        __hide_text_after_seconds("project_add_error_label", "No customer selected!", 3)
        return
    project_name = dpg.get_value("project_add_name_input")
    if project_name == "":
        __hide_text_after_seconds(
            "project_add_error_label", "Cannot have blank project name!", 3
        )
        return
    git_id = dpg.get_value("project_add_git_input")

    __hide_text_after_seconds(
        "project_add_error_label", "Adding project to DB!", 3, error=False
    )
    db.queue_task(
        "insert_project",
        {
            "customer_name": customer_name,
            "project_name": project_name,
            "git_id": git_id,
        },
    )
    __post_user_input()
    __log_message(
        f"Project {project_name} for customer {customer_name} added to DB",
        type="INFO",
    )


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
    new_git_id = dpg.get_value("project_update_git_input")

    # Success Case:
    __hide_text_after_seconds(
        "project_update_error_label", "Updating project in DB!", 3, error=False
    )
    db.queue_task(
        "update_project",
        {
            "customer_name": customer_name,
            "project_name": project_name,
            "new_project_name": new_project_name,
            "new_git_id": new_git_id,
        },
    )
    __post_user_input()
    __log_message(
        f"Project {project_name} renamed to {new_project_name} with git id {new_git_id}",
        type="INFO",
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

    __hide_text_after_seconds(
        "project_delete_error_label", "Disabling project in DB!", 3, error=False
    )
    db.queue_task(
        "delete_project", {"customer_name": customer_name, "project_name": project_name}
    )
    __post_user_input()
    __log_message(
        f"Project {project_name} disabled in the DB",
        type="INFO",
    )


def add_bonus_data(sender, app_data) -> None:
    amount = dpg.get_value("bonus_add_amount_input")
    start_date = dpg.get_value("bonus_add_start_date_input")

    if start_date == "":
        __hide_text_after_seconds(
            "bonus_add_error_label", "Cannot have blank start date!", 3
        )
        return

    __hide_text_after_seconds(
        "bonus_add_error_label", "Adding bonus to DB!", 3, error=False
    )
    db.queue_task("insert_bonus", {"amount": amount, "start_date": start_date})
    __post_user_input()
    __log_message(
        f"Bonus percent {amount} starting on {start_date} added to the DB",
        type="INFO",
    )


###
# UI
###
with dpg.window(label="Work Timer v3", width=WIDTH, height=HEIGHT):
    ## Input
    with dpg.collapsing_header(label="Extra", default_open=False):
        with dpg.collapsing_header(label="Input", default_open=False, indent=INDENT_1):
            with dpg.collapsing_header(
                label="Customers", default_open=False, indent=INDENT_2
            ):
                with dpg.collapsing_header(
                    label="Add Customer", default_open=False, indent=INDENT_2
                ):
                    dpg.add_input_text(
                        label="Customer Name", tag="customer_add_name_input"
                    )
                    dpg.add_input_int(label="Wage", tag="customer_add_wage_input")

                    with dpg.group(horizontal=True):
                        dpg.add_input_text(tag="customer_add_start_date_input")
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
                        tag="customer_add_start_button_popup",
                    ):
                        today_struct = __get_current_date_struct()
                        dpg.add_date_picker(
                            label="Start Date",
                            tag="customer_add_start_date_picker",
                            default_value=today_struct,
                        )
                        dpg.add_button(
                            label="Done",
                            callback=lambda: set_start_date("customer_add"),
                        )

                    add_save_button(add_customer_data, "customer_add", "Save")

                with dpg.collapsing_header(
                    label="Update Customer", default_open=False, indent=INDENT_2
                ):
                    dpg.add_combo(
                        [],
                        width=COMBO_WIDTH,
                        label="Customer Name",
                        tag="customer_update_name_dropdown",
                        callback=lambda: __update_text_input(
                            tag="customer_update_name_dropdown"
                        ),
                    )
                    dpg.add_input_text(
                        label="New Name",
                        tag="customer_update_customer_name_input",
                    )
                    dpg.add_input_int(
                        label="Wage",
                        tag="customer_update_wage_input",
                    )
                    add_save_button(update_customer_data, "customer_update", "Update")

                with dpg.collapsing_header(
                    label="Remove Customer", default_open=False, indent=INDENT_2
                ):
                    dpg.add_combo(
                        [],
                        default_value="",
                        width=COMBO_WIDTH,
                        label="Customer Name",
                        tag="customer_delete_name_dropdown",
                    )
                    add_save_button(delete_customer_data, "customer_delete", "Remove")

            with dpg.collapsing_header(
                label="Project", default_open=False, indent=INDENT_2
            ):
                with dpg.collapsing_header(
                    label="Add Project", default_open=False, indent=INDENT_2
                ):
                    dpg.add_combo(
                        [],
                        width=COMBO_WIDTH,
                        label="Customer Name",
                        tag="project_add_customer_name_dropdown",
                    )
                    dpg.add_input_text(
                        label="Project Name", tag="project_add_name_input"
                    )
                    dpg.add_input_int(
                        label="Git ID (Opt.)", tag="project_add_git_input"
                    )
                    add_save_button(add_project_data, "project_add", "Save")

                with dpg.collapsing_header(
                    label="Update Project", default_open=False, indent=INDENT_2
                ):
                    dpg.add_combo(
                        [],
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
                        callback=lambda: __update_text_input(
                            tag="project_update_project_name_dropdown"
                        ),
                    )
                    dpg.add_input_text(
                        label="New Name", tag="project_update_name_input"
                    )
                    dpg.add_input_int(
                        label="New Git-ID", tag="project_update_git_input"
                    )

                    add_save_button(update_project_data, "project_update", "Update")

                with dpg.collapsing_header(
                    label="Remove Project", default_open=False, indent=INDENT_2
                ):
                    dpg.add_combo(
                        [],
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

            with dpg.collapsing_header(
                label="Bonuses", default_open=False, indent=INDENT_2
            ):
                with dpg.collapsing_header(
                    label="Add Bonus", default_open=False, indent=INDENT_2
                ):
                    dpg.add_input_float(
                        label="Bonus Amount", tag="bonus_add_amount_input"
                    )
                    with dpg.group(horizontal=True):
                        dpg.add_input_text(tag="bonus_add_start_date_input")
                        dpg.add_image_button(
                            texture_tag=icon_calendar,
                            tag="bonus_add_start_date_button",
                            width=14,
                            height=14,
                        )
                        dpg.add_text("Start Date")

                    with dpg.popup(
                        parent="bonus_add_start_date_button",
                        mousebutton=dpg.mvMouseButton_Left,
                        modal=True,
                        tag="bonus_add_start_button_popup",
                    ):
                        today_struct = __get_current_date_struct()
                        dpg.add_date_picker(
                            label="Start Date",
                            tag="bonus_add_start_date_picker",
                            default_value=today_struct,
                        )
                        dpg.add_button(
                            label="Done", callback=lambda: set_start_date("bonus_add")
                        )

                    add_save_button(add_bonus_data, "bonus_add", "Save")

        ## Settings
        with dpg.collapsing_header(
            label="Settings", default_open=False, indent=INDENT_1
        ):
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
                    data_type_options = ["Time", "Bonus Wage"]
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
        with dpg.collapsing_header(
            label="Queries",
            default_open=False,
            indent=INDENT_1,
        ):
            dpg.add_button(
                callback=lambda: open_query_popup(), label="Open Query Window"
            )

        # Logg Section
        with dpg.collapsing_header(label="Logs", default_open=False, indent=INDENT_1):
            dpg.add_input_text(
                tag="log_box",
                multiline=True,
                readonly=True,
                width=WIDTH - 30,
                height=200,
            )

    with dpg.collapsing_header(
        label="Customers", default_open=True, tag="customers_section"
    ):
        with dpg.child_window(
            tag="customer_ui_section", autosize_x=True, autosize_y=True, border=False
        ):
            pass  # Placeholder for dynamic content

frame = dpg.create_viewport(
    title="Work Timer v3",
    width=WIDTH + 15,
    height=HEIGHT + 50,
    small_icon="graphics\\program_logo.ico",
    large_icon="graphics\\program_logo.ico",
)
dpg.setup_dearpygui()
dpg.show_viewport()

dpg.set_frame_callback(1, render_customer_project_ui)
dpg.set_frame_callback(2, populate_pre_log)
INIT = False


last_update_time = time.time()


def periodic_update():
    """Function to periodically queue the update task."""
    global last_update_time, CURRENT_DATE, SELECTED_DATE
    current_time = time.time()
    if current_time - last_update_time >= 60:
        threading.Thread(target=run_update_ui_task, daemon=True).start()
        last_update_time = current_time

    current_date = datetime.now().date()
    if current_date > CURRENT_DATE:
        CURRENT_DATE = current_date
        SELECTED_DATE = current_date.strftime("%Y-%m-%d")


def run_update_ui_task():
    """Run the update UI task in a separate thread."""
    start_date, end_date, sel_type = __get_user_input()

    r_queue = queue.Queue()
    db.queue_task(
        "get_customer_ui_list",
        {"start_date": start_date, "end_date": end_date, "data_type": sel_type},
        response=r_queue,
    )
    df = r_queue.get()

    update_ui_from_df(df, sel_type)


def update_ui_from_df(df: pd.DataFrame, sel_type: str) -> None:
    """Update the UI with the data from the database."""

    for _, row in df.iterrows():
        customer_id = row["customer_id"]
        project_id = row["project_id"]

        tag = f"time_{customer_id}_{project_id}"
        if sel_type == "total_time":
            updated_text = f"Total: {row['total_time']} h"
        elif sel_type == "cost":
            updated_text = f"Total: {row['user_bonus']} SEK"
        else:
            updated_text = "Erronous value!"
        dpg.set_value(tag, updated_text)

    for customer_id in df["customer_id"].unique():
        if sel_type == "total_time":
            total_text = f"Total: {df[df['customer_id'] == customer_id]['total_time'].sum():.2f} h"
        elif sel_type == "cost":
            total_text = f"Total: {df[df['customer_id'] == customer_id]['user_bonus'].sum():.2f} SEK"
        else:
            total_text = "Erronous value!"
        dpg.set_value(f"total_{customer_id}", total_text)


# Main Dear PyGui loop
while dpg.is_dearpygui_running():
    db.process_queue()
    periodic_update()
    dpg.render_dearpygui_frame()

dpg.destroy_context()


###############################
### update old db to new db ###
###############################

# alter table time add git_id int, user_bonus float
# alter table dates drop column iso_year
# alter table projects add git_id int

# alter table customers add pat_token text, org_url text

# create trigger if not exists trigger_time_after_update
# after update on time
# for each row
# begin
#     update time
#     set
#         total_time = (julianday(new.end_time) - julianday(new.start_time)) * 24,
#         cost = new.wage * ((julianday(new.end_time) - julianday(new.start_time)) * 24),
#         user_bonus = new.bonus * new.wage * ((julianday(new.end_time) - julianday(new.start_time)) * 24)
#     where time_id = new.time_id;
# end;


# update values
# update time
# set wage = (
#     select ifnull(c.wage, 0)
#     from customers c
#     where c.customer_id = time.customer_id
#       and time.start_time between c.valid_from and ifnull(c.valid_to, '2099-12-31')
#     limit 1
# )
# where wage <> (
#     select ifnull(c.wage, 0)
#     from customers c
#     where c.customer_id = time.customer_id
#       and time.start_time between c.valid_from and ifnull(c.valid_to, '2099-12-31')
#     limit 1
# );
#
# alter table customers add column sort_order integer default = 1
#
# with ordered as (
#   select
#     customer_name,
#     row_number() over (order by customer_name) as new_position
#   from customers
# )
# update customers
# set sort_order = (
#   select new_position
#   from ordered
#   where ordered.customer_name = customers.customer_name
#   limit 1
# );
