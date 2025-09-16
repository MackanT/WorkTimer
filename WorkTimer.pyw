import dearpygui.dearpygui as dpg
from datetime import datetime, timedelta, date
import pandas as pd
import time

import argparse
import queue
import threading

import win32gui
import re
import os
import json
import random

from database import Database
from devops import DevOpsClient

from dataclasses import dataclass

###
# Constants
###
PROGRAM_NAME = "Work Timer v3"
DEVOPS_URL = "https://dev.azure.com/"

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

POPUP_WIDTH = 300
POPUP_HEIGHT = 100

TIME_ID = 0  # 0 = Day, 1 = Week, 2 = Month, 3 = Year, 4 = All-Time
TYPE_ID = 0  # 0 = Time, 1 = Bonus Wage
SELECTED_DATE = datetime.now().strftime("%Y-%m-%d")
CURRENT_DATE = datetime.now().date()

THEME_DF = {}
_apply_theme_timer = None

LOG_CONTENT = ""


@dataclass
class TableColumn:
    editable: bool = False
    pk: bool = False
    type: str = "str"


TABLE_IDS = {
    "time": {
        "time_id": TableColumn(pk=True, type="int"),
        "customer_id": TableColumn(type="int"),
        "customer_name": TableColumn(),
        "project_id": TableColumn(editable=True, type="project_id"),  # Special
        "project_name": TableColumn(),
        "start_time": TableColumn(editable=True, type="datetime"),
        "end_time": TableColumn(editable=True, type="datetime"),
        "date_key": TableColumn(type="int"),
        "total_time": TableColumn(type="float"),
        "cost": TableColumn(type="float"),
        "bonus": TableColumn(type="float"),
        "wage": TableColumn(type="int"),
        "comment": TableColumn(editable=True),
        "git_id": TableColumn(editable=True, type="int"),
        "user_bonus": TableColumn(type="float"),
    },
    "customers": {
        "customer_id": TableColumn(pk=True, type="int"),
        "customer_name": TableColumn(),
        "start_date": TableColumn(type="date"),
        "wage": TableColumn(type="int"),
        "valid_from": TableColumn(type="date"),
        "valid_to": TableColumn(type="date"),
        "is_current": TableColumn(type="bool"),
        "inserted_at": TableColumn(type="datetime"),
        "pat_token": TableColumn(editable=True),
        "org_url": TableColumn(editable=True),
        "sort_order": TableColumn(editable=False, type="int"),
    },
    "projects": {
        "project_id": TableColumn(pk=True, type="int"),
        "project_name": TableColumn(),
        "customer_id": TableColumn(type="int"),
        "is_current": TableColumn(type="bool"),
        "git_id": TableColumn(editable=True, type="str"),
    },
    "bonus": {
        "bonus_id": TableColumn(pk=True, type="int"),
        "bonus_percent": TableColumn(type="float"),
        "start_date": TableColumn(type="date"),
        "end_date": TableColumn(type="date"),
    },
    "dates": {
        "date_key": TableColumn(pk=True, type="int"),
        "date": TableColumn(type="date"),
        "year": TableColumn(type="int"),
        "month": TableColumn(type="int"),
        "week": TableColumn(type="int"),
        "day": TableColumn(type="int"),
    },
}


###
# Argument Paring
###
def parse_args():
    parser = argparse.ArgumentParser(description=PROGRAM_NAME)
    parser.add_argument(
        "--db", type=str, default="data_dpg", help="Database name to load"
    )
    return parser.parse_args()


###
# SQL-Backend logic
###

args = parse_args()
db_file = f"{args.db}.db"

db = Database(db_file)
db.initialize_db()


###
# DepOps Connection
###
do_con = {}
df_do = db.fetch_query(
    "select distinct customer_name, pat_token, org_url from customers where pat_token is not null and org_url is not null"
)
try:
    for _, row in df_do.iterrows():
        if row["org_url"].lower() in ["", "none", "null"] or row[
            "pat_token"
        ].lower() in ["", "none", "null"]:
            db.pre_run_log.append(
                f"Found null row in valid connections for customer: {row['customer_name']}. Skipping connection attempt"
            )
            continue
        org_url = f"{DEVOPS_URL}{row['org_url']}"
        do_con[row["customer_name"]] = DevOpsClient(row["pat_token"], org_url)
        do_con[row["customer_name"]].connect()
        db.pre_run_log.append(
            f"DevOps connection established to {row['customer_name']} for organization {row['org_url']}"
        )
except Exception as e:
    print(e)  ## TODO someting nicer here...!
dpg.create_context()

## Image Input
width, height, channels, data = dpg.load_image("graphics\\icon_calendar.png")
with dpg.texture_registry():
    icon_calendar = dpg.add_static_texture(width, height, data)

input_focused = False


###
# Detect open/closed-state of collapsing customer headers - needed to counteract bug in DPG
###
header_state = {}


def on_header_change(tag: str):
    """Updates the stored state of the tag into the dict header_state"""
    new_state = dpg.get_value(tag)
    header_state[tag] = not new_state


def is_window_minimized(title: str = "Work Timer v3") -> bool:
    """
    Returns True if the window with the given title is minimized, otherwise False.

    Args:
        title (str): The window title to check.

    Returns:
        bool: True if minimized, False otherwise.
    """
    hwnd = win32gui.FindWindow(None, title)
    if hwnd:
        return win32gui.IsIconic(hwnd)  # Returns True if minimized
    return False


def __fix_headers() -> None:
    """Sets header state for customer projects as bug in DPG causes them to auto-close on minimiziation of the window"""
    for tag in header_state:
        dpg.set_value(tag, header_state[tag])


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


def __populate_ui_settings():
    global THEME_DF
    __apply_default_theme()

    for _, row in THEME_DF.iterrows():
        name, desc, r, g, b, a = row
        color_tag = f"color_square_{name}"

        with dpg.group(horizontal=True, parent="ui_settings"):
            dpg.add_color_edit(
                default_value=[r, g, b, a],
                tag=color_tag,
                width=30,
                callback=update_theme_df,
                user_data=name,
                no_drag_drop=True,
                no_inputs=True,
            )
            dpg.add_text(desc)

    # Add save button to write THEME_DF to DB
    def save_theme_to_db():
        for _, row in THEME_DF.iterrows():
            name, desc, r, g, b, a = row
            query = f"UPDATE settings SET red = {r}, green = {g}, blue = {b}, alpha = {a} WHERE setting_name = '{name}' and setting_type = 'ui_color'"
            db.queue_task("run_query", {"query": query})
        __log_message("Theme settings saved to database.", type="INFO")

    def reset_theme_colors():
        __apply_default_theme()
        # Update color edits in the UI to match THEME_DF
        for _, row in THEME_DF.iterrows():
            name, desc, r, g, b, a = row
            color_tag = f"color_square_{name}"
            dpg.set_value(color_tag, [r, g, b, a])

        __log_message("Theme colors reset to database values.", type="INFO")

    dpg.add_spacer(height=5, parent="ui_settings")

    with dpg.group(horizontal=True, parent="ui_settings"):
        dpg.add_button(label="Save color changes", callback=save_theme_to_db)

        dpg.add_button(
            label="Reset Changes",
            callback=reset_theme_colors,
        )

    dpg.add_spacer(height=5, parent="ui_settings")


def update_theme_df(sender, app_data, user_data):
    idx = THEME_DF.index[THEME_DF["setting_name"] == user_data].tolist()
    if idx:
        # Convert r, g, b to int in [0,255] range, alpha stays as is
        r, g, b, a = app_data
        r = int(r * 255)
        g = int(g * 255)
        b = int(b * 255)
        a = int(a * 255)
        THEME_DF.loc[idx[0], ["red", "green", "blue", "alpha"]] = [r, g, b, a]

    debounce_apply_theme(THEME_DF)


def debounce_apply_theme(theme_df, delay=0.3):
    global _apply_theme_timer
    if _apply_theme_timer is not None:
        _apply_theme_timer.cancel()

    def call_theme():
        apply_theme(theme_df)

    _apply_theme_timer = threading.Timer(delay, call_theme)
    _apply_theme_timer.start()


def __populate_pre_log():
    for line in db.pre_run_log:
        __log_message(line, type="INFO")


def __log_message(message: str, type: str = "INFO") -> None:
    global LOG_CONTENT
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_log = (
        f"{timestamp} [{type}] - {message}\n{LOG_CONTENT}"
        if LOG_CONTENT
        else f"{timestamp} [{type}] - {message}"
    )
    LOG_CONTENT = new_log
    if dpg.does_item_exist("log_box"):
        dpg.set_value("log_box", LOG_CONTENT)


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
        db.queue_task(
            "get_customer_update", {"customer_name": cur_val}, response=r_queue
        )
        df = r_queue.get()
        df = df.iloc[0] if isinstance(df, pd.DataFrame) else df
        new_wage = int(df["wage"])
        org_url = df["org_url"]
        pat_token = df["pat_token"]

        dpg.set_value("customer_update_wage_input", new_wage)
        dpg.set_value("customer_update_devops_url_input", org_url)
        dpg.set_value("customer_update_devops_pat_input", pat_token)
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


def __autoset_query_window(table_id: int = None, table_name: str = None) -> None:
    if table_id:
        table_name = dpg.get_item_label(table_id)

    match table_name:
        case "time":
            sql_input = (
                "select\n"
                "     time_id\n"
                "    ,start_time, end_time, round(total_time, 2) as total_time\n"
                "    ,customer_id, customer_name\n"
                "    ,project_id, project_name\n"
                "    ,git_id, comment\n"
                "from time\n"
                "order by time_id desc\n"
                "limit 100"
            )
        case "customers":
            sql_input = (
                "select\n"
                "     customer_id\n"
                "    ,customer_name\n"
                "    ,wage\n"
                "    ,org_url\n"
                "    ,pat_token\n"
                "from customers\n"
                "where is_current = 1"
            )
        case "projects":
            sql_input = (
                "select\n"
                "     project_id\n"
                "    ,project_name\n"
                "    ,customer_id\n"
                "    ,git_id\n"
                "from projects\n"
                "where is_current = 1"
            )
        case "weekly":
            sql_input = (
                "select\n"
                "     t.customer_name\n"
                "    ,t.project_name\n"
                "    ,round(sum(t.total_time), 2) as total_time\n"
                "from time t\n"
                "left join dates d on d.date_key = t.date_key\n"
                "where d.year = cast(strftime('%Y', 'now') as integer)\n"
                "and d.week = ( select week from dates where date = date('now') limit 1 )\n"
                "group by t.customer_name, t.project_name\n"
                "having sum(t.total_time) > 0\n"
                "order by 1, 2\n"
            )
        case "monthly":
            sql_input = (
                "select\n"
                "     t.customer_name\n"
                "    ,t.project_name\n"
                "    ,round(sum(t.total_time), 2) as total_time\n"
                "from time t\n"
                "left join dates d on d.date_key = t.date_key\n"
                "where d.year = cast(strftime('%Y', 'now') as integer)\n"
                "and d.month = cast(strftime('%m', 'now') as integer)\n"
                "group by customer_name, project_name\n"
                "having sum(total_time) > 0\n"
                "order by 1, 2\n"
            )
        case _:
            sql_input = f"select * from {table_name}"

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


def render_customer_project_ui():
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
        header_tag = f"header_{customer_id}"
        header_id = dpg.add_collapsing_header(
            label=customer_name,
            default_open=True,
            indent=10,
            parent="customer_ui_section",
            tag=header_tag,
        )

        def make_header_callback(tag):
            return lambda s, a: on_header_change(tag)

        handler_tag = f"header_{customer_id}_handler"
        if not dpg.does_item_exist(handler_tag):
            with dpg.item_handler_registry(tag=handler_tag) as handler:
                dpg.add_item_activated_handler(
                    callback=make_header_callback(header_tag)
                )
            dpg.bind_item_handler_registry(header_id, handler_tag)

        header_state[header_tag] = True

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
                tag=f"checkbox_{customer_id}_{project_id}",
                user_data=(customer_id, project_id, customer_name),
                default_value=initial_state,
                parent=group_id,
            )

            dpg.add_text("", tag=f"time_{customer_id}_{project_id}", parent=group_id)
        # dpg.add_spacer(height=10, parent="customer_ui_section")

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
            width=WIDTH / 1.5,
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
                dpg.add_button(
                    label="Delete",
                    callback=lambda: delete_popup_action(
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
                show_message_popup(status)

    dpg.delete_item(window_tag)
    run_update_ui_task()


def cancel_popup_action(sender, app_data, customer_id, project_id, window_tag):
    dpg.set_value(sender, not app_data)
    dpg.delete_item(window_tag)
    run_update_ui_task()


def delete_popup_action(sender, app_data, customer_id, project_id, window_tag):
    db.delete_time_row(int(customer_id), int(project_id))
    dpg.delete_item(window_tag)
    run_update_ui_task()


def show_message_popup(message: str = None, popup_type: str = "Error") -> None:
    # Get the current viewport size
    vp_width, vp_height = dpg.get_viewport_width(), dpg.get_viewport_height()

    # Calculate centered position
    pos_x = (vp_width - POPUP_WIDTH) // 2
    pos_y = (vp_height - POPUP_HEIGHT) // 2

    if not dpg.does_item_exist("message_popup"):
        with dpg.window(
            label=popup_type,
            tag="message_popup",
            width=POPUP_WIDTH,
            height=POPUP_HEIGHT,
            pos=(pos_x, pos_y),
            no_close=True,
            no_collapse=True,
            no_move=True,
        ):
            dpg.add_text(message, wrap=POPUP_WIDTH - 20, tag="popup_text")
            dpg.add_button(label="OK", callback=lambda: dpg.hide_item("message_popup"))
            dpg.configure_item("message_popup", show=True)
    else:
        dpg.configure_item("message_popup", show=True)
        dpg.set_value("popup_text", message)
        dpg.set_item_pos("message_popup", [pos_x, pos_y])

    dpg.focus_item("message_popup")


## Toggle toggle popups
def toggle_popup(tag, open_func, close_func):
    if dpg.does_item_exist(tag):
        close_func()
    else:
        open_func()


def toggle_query_popup():
    toggle_popup("query_popup_window", open_query_popup, close_query_popup)


def toggle_log_popup():
    toggle_popup("log_popup_window", open_log_popup, close_log_popup)


## Close Tab popups
def close_popup(tag: str):
    dpg.set_viewport_width(WIDTH + 15)  # Restore original width
    dpg.set_viewport_height(HEIGHT + 50)  # Restore original height if changed
    dpg.delete_item(tag)
    switch_back_to_previous_tab()


def close_query_popup():
    close_popup("query_popup_window")


def close_log_popup():
    close_popup("log_popup_window")


## Open Tab Popups
def open_query_popup() -> None:
    query_popup_tag = "query_popup_window"
    dpg.set_viewport_width(QUERY_WIDTH + 20)
    if dpg.does_item_exist(query_popup_tag):
        dpg.delete_item(query_popup_tag)
    with dpg.window(
        label="Query Results",
        tag=query_popup_tag,
        width=QUERY_WIDTH,
        height=600,
        modal=False,
        no_close=True,
        no_collapse=True,
        no_move=True,
    ):
        dpg.add_button(
            label="Close",
            callback=close_query_popup,
        )

        with dpg.group():
            available_queries = [
                "time",
                "customers",
                "projects",
                "bonus",
                "weekly",
                "monthly",
            ]
            with dpg.group(horizontal=True):
                dpg.add_text("Available tables:")
                for table in available_queries:
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
            if not dpg.does_item_exist("query_input_handler"):
                with dpg.item_handler_registry(tag="query_input_handler") as handler:
                    dpg.add_item_activated_handler(
                        callback=on_input_focus
                    )  # Triggered when user clicks into it
                    dpg.add_item_deactivated_after_edit_handler(
                        callback=on_input_unfocus
                    )  # Triggered when they click out

                dpg.bind_item_handler_registry("query_input", "query_input_handler")

        # Box for displaying tabular data
        dpg.add_text("Tabular Data:")

        handle_query_input()

    with dpg.handler_registry():
        dpg.add_key_press_handler(key=dpg.mvKey_F5, callback=handle_query_input)


## Log popup
def open_log_popup():
    log_popup_tag = "log_popup_window"
    dpg.set_viewport_width(QUERY_WIDTH + 20)
    if dpg.does_item_exist(log_popup_tag):
        dpg.delete_item(log_popup_tag)
    with dpg.window(
        label="Log Viewer",
        tag=log_popup_tag,
        width=QUERY_WIDTH,
        height=600,
        modal=False,
        no_close=True,
        no_collapse=True,
        no_move=True,
    ):
        dpg.add_button(
            label="Close",
            callback=close_log_popup,
        )
        dpg.add_input_text(
            tag="log_box",
            multiline=True,
            readonly=True,
            width=QUERY_WIDTH - 30,
            height=HEIGHT,
            default_value=LOG_CONTENT,
        )


def _add_project_name(popup_tag: str, customer_id: int, project_name: str) -> dict:
    sql_query = f"select distinct project_id, project_name from projects where customer_id = {customer_id} and is_current = 1"

    r_queue = queue.Queue()
    db.queue_task("run_query", {"query": sql_query}, response=r_queue)
    df = r_queue.get()

    # After fetching the DataFrame df with columns project_id and project_name
    project_options = [
        {"id": row["project_id"], "name": row["project_name"]}
        for _, row in df.iterrows()
    ]
    project_names = [p["name"] for p in project_options]
    project_id_map = {p["name"]: p["id"] for p in project_options}

    # Add the combo (dropdown)
    dpg.add_combo(
        project_names,
        label="Project",
        tag=f"{popup_tag}_project_id_input",
        default_value=project_name,
    )

    return project_id_map


def _on_edit_row_ok(sender, app_data, user_data: str):
    (
        popup_tag,
        editable_cols,
        table_data,
        table_name,
        table_id,
        key_table,
        project_dict,
    ) = user_data

    vals = []
    errors = []
    for col in editable_cols:
        value = dpg.get_value(f"{popup_tag}_{col}_input")
        meta = table_data[col]

        if meta.type == "int":
            try:
                int(value)
            except Exception:
                errors.append(f"{col} must be an integer.")
        elif meta.type == "float":
            try:
                float(value)
            except Exception:
                errors.append(f"{col} must be a float.")
        elif meta.type == "datetime":
            try:
                datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except Exception:
                errors.append(f"{col} must be in YYYY-MM-DD HH:MM:SS format.")
        elif meta.type == "date":
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except Exception:
                errors.append(f"{col} must be in YYYY-MM-DD format.")
        elif meta.type == "project_id":
            value = project_dict[value]

        vals.append((col, value))

    if errors:
        dpg.set_value(f"{popup_tag}_popup_text", "\n".join(errors))
        return

    if table_name == "customers":
        pat_token = ""
        org_url = ""
        for val in vals:
            if val[0] == "pat_token":
                pat_token = val[1]
            elif val[0] == "org_url":
                org_url = val[1]

        try:
            full_org_url = f"{DEVOPS_URL}{org_url}"
            devops_client = DevOpsClient(pat_token, full_org_url)
            devops_client.connect()
        except Exception as e:
            dpg.set_value(f"{popup_tag}_popup_text", "Failure connecting to DevOps!")
            return

    sql_query = f"update {table_name} set "
    for val_set in vals:
        data_type = table_data[val_set[0]].type
        escape = "'" if data_type in ["date", "datetime", "str"] else ""
        sql_query += f"{val_set[0]} = {escape}{val_set[1]}{escape}, "
    sql_query = sql_query[:-2] + f" where {table_id} = {key_table}"

    db.queue_task("run_query", {"query": sql_query})
    __log_message(
        f"Updating row: {table_id} = {key_table} in {table_name} with command:\n{sql_query}"
    )

    dpg.delete_item(popup_tag)


def _on_edit_row_cancel(sender, app_data, user_data: str):
    dpg.delete_item(user_data)


def clb_selectable(sender, app_data, user_data):
    row, table_name, num_cols = user_data

    popup_tag = f"row_popup_{row}"

    # Extract columns + data about editable table
    table_data = TABLE_IDS.get(table_name)
    if table_data is None:
        __log_message(f"Trying to edit undefined table {table_name}!")
        dpg.set_value(sender, False)
        return
    table_id = next(col for col, meta in table_data.items() if meta.pk)
    all_cols = [col for col, meta in table_data.items()]
    editable_cols = [col for col, meta in table_data.items() if meta.editable]

    # Ensure PK-column in selection and extract selected rows PK-value
    dpg_table_cols = []
    dpg_table_values = []
    for i in range(num_cols):
        dpg_table_cols.append(dpg.get_item_label(f"col_{i}"))

    if table_id not in dpg_table_cols:
        __log_message(
            f"Trying to edit table {table_name} without including table_key: {table_id}!"
        )
        dpg.set_value(sender, False)
        return
    else:
        for i in range(num_cols):
            dpg_table_values.append(dpg.get_item_label(f"row{row}_column{i}"))
    dpg_index = dpg_table_cols.index(table_id)
    key_table = dpg_table_values[dpg_index]

    # Get original data from database for row
    sql_query = (
        f"select {', '.join(all_cols)} from {table_name} where {table_id} = {key_table}"
    )
    r_queue = queue.Queue()
    db.queue_task("run_query", {"query": sql_query}, response=r_queue)
    df = r_queue.get()

    # Remove popup if it already exists
    if dpg.does_item_exist(popup_tag):
        dpg.delete_item(popup_tag)

    vp_width, vp_height = dpg.get_viewport_width(), dpg.get_viewport_height()

    popup_width = QUERY_WIDTH / 4
    popup_height = 25 * (len(editable_cols) + 4)

    # Calculate centered position
    pos_x = (vp_width - POPUP_WIDTH) // 2
    pos_y = (vp_height - POPUP_HEIGHT) // 2

    # (Re)creates popup
    with dpg.window(
        label="Edit Cell",
        tag=popup_tag,
        modal=True,
        no_close=True,
        width=popup_width,
        height=popup_height,
        pos=(pos_x, pos_y),
    ):
        dpg.add_text(f"Updating row in table: {table_name}")

        project_dict = None
        for col in editable_cols:
            meta = table_data[col]
            # Get the value from df for this column (assuming single row)
            default_value = df[col].iloc[0] if col in df.columns else ""
            input_tag = f"{popup_tag}_{col}_input"

            if meta.type == "int":
                dpg.add_input_int(
                    label=col.replace("_", " ").title(),
                    tag=input_tag,
                    default_value=int(default_value)
                    if pd.notnull(default_value)
                    else 0,
                )
            elif meta.type == "float":
                dpg.add_input_float(
                    label=col.replace("_", " ").title(),
                    tag=input_tag,
                    default_value=float(default_value)
                    if pd.notnull(default_value)
                    else 0.0,
                )
            elif meta.type == "str":
                dpg.add_input_text(
                    label=col.replace("_", " ").title(),
                    tag=input_tag,
                    default_value=str(default_value)
                    if pd.notnull(default_value)
                    else "",
                )
            elif meta.type == "datetime":
                dpg.add_input_text(
                    label=col.replace("_", " ").title(),
                    tag=input_tag,
                    default_value=str(default_value)
                    if pd.notnull(default_value)
                    else "",
                    hint="YYYY-MM-DD HH:MM:SS",
                )
            elif meta.type == "date":
                dpg.add_input_text(
                    label=col.replace("_", " ").title(),
                    tag=input_tag,
                    default_value=str(default_value)
                    if pd.notnull(default_value)
                    else "",
                    hint="YYYY-MM-DD",
                )
            elif meta.type == "project_id":
                project_dict = _add_project_name(
                    popup_tag=popup_tag,
                    customer_id=df["customer_id"].iloc[0],
                    project_name=df["project_name"].iloc[0],
                )

        dpg.add_text("", color=WARNING_RED, tag=f"{popup_tag}_popup_text")
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="OK",
                callback=_on_edit_row_ok,
                user_data=(
                    popup_tag,
                    editable_cols,
                    table_data,
                    table_name,
                    table_id,
                    key_table,
                    project_dict,
                ),
            )
            dpg.add_button(
                label="Cancel", callback=_on_edit_row_cancel, user_data=popup_tag
            )

    dpg.set_value(sender, False)


def handle_query_input():
    # Always try to get the query from the popup input if it exists
    if dpg.does_item_exist("query_input"):
        query_text = dpg.get_value("query_input")
        r_queue = queue.Queue()
        db.queue_task("run_query", {"query": query_text}, response=r_queue)
        df = r_queue.get()

        if isinstance(df, Exception):
            show_message_popup(f"Error: {str(df)}")
            return
        elif isinstance(df, list) and len(df) == 0:
            show_message_popup("Command completed successfully!", popup_type="Success")
            return
        elif isinstance(df, pd.errors.DatabaseError):
            show_message_popup(df)
            return
        elif df is None or not isinstance(df, pd.DataFrame):
            __log_message(
                "Query Error: No data returned! Evaluate and find when we get here!"
            )
            return

        # Extract the table name from the query
        def extract_table_name(query_text: str) -> str:
            match = re.search(r"from\s+([^\s;]+)", query_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
            return "unknown_table"

        table_name = extract_table_name(query_text)

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
            # ) as selectablecells:
        ):
            char_width = 8
            min_width = 60
            max_width = 300
            num_cols = len(df.columns)
            for i, col in enumerate(df.columns):
                max_len = max([len(str(x)) for x in df[col].values] + [len(str(col))])
                col_width = max(min_width, max_len * char_width)
                col_width = min(col_width, max_width)
                dpg.add_table_column(
                    label=col,
                    init_width_or_weight=col_width,
                    tag=f"col_{i}",
                )
            arr = df.to_numpy()
            for i in range(df.shape[0]):
                with dpg.table_row():
                    for j in range(df.shape[1]):
                        # dpg.add_text(str(arr[i, j]))
                        cell_value = str(arr[i, j])
                        dpg.add_selectable(
                            label=cell_value,
                            tag=f"row{i}_column{j}",
                            span_columns=True,
                            callback=clb_selectable,
                            user_data=(i, table_name, num_cols),
                        )


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
    dpg.set_value("customer_add_devops_url_input", "")
    dpg.set_value("customer_add_devops_pat_input", "")
    # Update Customer
    dpg.set_value("customer_update_name_dropdown", "")
    dpg.set_value("customer_update_customer_name_input", "")
    dpg.set_value("customer_update_wage_input", 0)
    dpg.set_value("customer_update_devops_url_input", "")
    dpg.set_value("customer_update_devops_pat_input", "")
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


def __validate_devops_inputs(tag_type: str, org_url: str, pat_token: str) -> bool:
    if (org_url and not pat_token) or (not org_url and pat_token):
        rand = random.randint(0, 10)
        def_msg = "Both Org-URL and PAT-Token must be specified!"
        if rand < 3:
            def_msg = "You can't have one without the other!"
        __hide_text_after_seconds(
            f"customer_{tag_type}_error_label",
            def_msg,
            3,
        )
        return False
    if org_url and pat_token:
        try:
            full_org_url = f"{DEVOPS_URL}{org_url}"
            devops_client = DevOpsClient(pat_token, full_org_url)
            devops_client.connect()
        except Exception as e:
            __log_message(
                f"Failed to add Customer, error connecting with specified DevOps connection: {str(e)}",
                type="ERROR",
            )
            __hide_text_after_seconds(
                f"customer_{tag_type}_error_label",
                "Org-URL and PAT-Token fails connection!",
                3,
            )
            return False

    return True


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

    org_url = dpg.get_value("customer_add_devops_url_input")
    pat_token = dpg.get_value("customer_add_devops_pat_input")

    if not __validate_devops_inputs("add", org_url, pat_token):
        return

    ## Case Success:
    if __is_valid_date(start_date):
        __hide_text_after_seconds(
            "customer_add_error_label", "Adding customer to DB!", 3, error=False
        )
        db.queue_task(
            "insert_customer",
            {
                "customer_name": customer_name,
                "start_date": start_date,
                "wage": amount,
                "org_url": org_url,
                "pat_token": pat_token,
            },
        )
        __update_dropdown("customer_dropdown")
        __post_user_input()
        add_msg = ""
        if org_url and pat_token:
            add_msg = f" with org URL {org_url} and PAT token {pat_token}."
        __log_message(
            f"Customer {customer_name} added to DB with start date {start_date} and wage {amount}. {add_msg}",
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
    pat_token = dpg.get_value("customer_update_devops_pat_input")
    org_url = dpg.get_value("customer_update_devops_url_input")

    if not __validate_devops_inputs("update", org_url, pat_token):
        return

    __hide_text_after_seconds(
        "customer_update_error_label", "Updating customer in DB!", 3, error=False
    )
    db.queue_task(
        "update_customer",
        {
            "customer_name": customer_name,
            "new_customer_name": new_customer_name,
            "wage": customer_wage,
            "org_url": org_url,
            "pat_token": pat_token,
        },
    )
    __update_dropdown("customer_dropdown")
    __post_user_input()
    add_msg = ""
    if org_url and pat_token:
        add_msg = f" with org URL {org_url} and PAT token {pat_token}."
    __log_message(
        f"Customer {customer_name} in DB renamed to {new_customer_name} with wage {customer_wage}. {add_msg}",
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

previous_tab = "settings_tab"  # Default tab on startup


def switch_back_to_previous_tab():
    global previous_tab
    tab_id = dpg.get_alias_id(previous_tab)
    dpg.set_value("main_tab_bar", tab_id)


def tab_selected_callback(sender, app_data):
    global previous_tab

    tab_tag = dpg.get_item_alias(app_data)
    if tab_tag not in ["query_tab", "logs_tab"]:
        previous_tab = tab_tag

    if tab_tag == "query_tab":
        toggle_query_popup()
    elif tab_tag == "logs_tab":
        toggle_log_popup()


with dpg.window(label="Work Timer v3", width=WIDTH, height=HEIGHT):
    with dpg.tab_bar(callback=tab_selected_callback, tag="main_tab_bar"):
        with dpg.tab(label="Settings", tag="settings_tab"):
            dpg.add_text("Settings")
        with dpg.tab(label="Customers", tag="customers_tab"):
            dpg.add_text("Customer Management")
        with dpg.tab(label="Projects", tag="projects_tab"):
            dpg.add_text("Project Management")
        with dpg.tab(label="Bonuses", tag="bonuses_tab"):
            dpg.add_text("Bonus Management")
        with dpg.tab(label="UI", tag="ui_tab"):
            dpg.add_text("Customize the UI settings:")
        with dpg.tab(label="Query Editor", tag="query_tab"):
            pass  # No content needed, acts as a button
        with dpg.tab(label="Logs", tag="logs_tab"):
            dpg.add_text("Log Viewer")

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

                    dpg.add_input_text(
                        label="DevOps Org. URL", tag="customer_add_devops_url_input"
                    )
                    dpg.add_input_text(
                        label="DevOps PAT", tag="customer_add_devops_pat_input"
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
                    dpg.add_input_text(
                        label="DevOps Org. URL", tag="customer_update_devops_url_input"
                    )
                    dpg.add_input_text(
                        label="DevOps PAT", tag="customer_update_devops_pat_input"
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
                        default_value=today_struct,
                        callback=on_date_selected,
                        tag="settings_date_picker",
                    )

        with dpg.collapsing_header(
            label="UI", default_open=True, indent=INDENT_1, tag="ui_settings"
        ):
            dpg.add_text("Customize the UI settings:")
            pass

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


def __validate_db():
    err_msg = ""

    r_queue = queue.Queue()
    db.queue_task(
        "run_query",
        {
            "query": "select count(*) as count from bonus where current_timestamp between start_date and coalesce(end_date, '2999-12-31')"
        },
        response=r_queue,
    )
    df = r_queue.get()

    if df["count"].iloc[0] != 1:
        err_msg += "Found no valid bonus set! Add one before using the program!"

    if err_msg != "":
        show_message_popup(err_msg)


def __apply_default_theme():
    global THEME_DF
    r_queue = queue.Queue()
    db.queue_task(
        "run_query",
        {
            "query": "select setting_name, setting_description, red, green, blue, alpha from settings where setting_type = 'ui_color'"
        },
        response=r_queue,
    )
    THEME_DF = r_queue.get()
    apply_theme(THEME_DF)


def apply_theme(THEME_DF: pd.DataFrame):
    theme_colors = {}
    for _, row in THEME_DF.iterrows():
        name, _, red, green, blue, alpha = row
        mv_type = eval(f"dpg.{name}")
        theme_colors[mv_type] = (red, green, blue, alpha)

    # Unbind current theme
    dpg.bind_theme(None)
    # Create and bind new theme
    with dpg.theme() as new_theme:
        with dpg.theme_component(dpg.mvAll):
            for key, value in theme_colors.items():
                dpg.add_theme_color(key, value)
    dpg.bind_theme(new_theme)


frame = dpg.create_viewport(
    title=PROGRAM_NAME,
    width=WIDTH + 15,
    height=HEIGHT + 50,
    small_icon="graphics\\program_logo.ico",
    large_icon="graphics\\program_logo.ico",
)

dpg.setup_dearpygui()
dpg.show_viewport()

dpg.set_frame_callback(1, render_customer_project_ui)
dpg.set_frame_callback(2, __populate_pre_log)
dpg.set_frame_callback(3, __validate_db)
dpg.set_frame_callback(4, __populate_ui_settings)
INIT = False

last_update_time = time.time()


def test_code():
    # do_con["Castellum"].get_workitem_level("feature")
    # alt_colors = {
    #     dpg.mvThemeCol_WindowBg: [0, 0, 0, 255],  # Black
    #     dpg.mvThemeCol_ChildBg: [255, 255, 255, 255],  # White
    #     dpg.mvThemeCol_Button: [255, 0, 0, 255],  # Red
    #     # ... add all theme keys you want to change
    # }
    1


# Debug test function without inputs
with dpg.handler_registry():
    dpg.add_key_press_handler(key=dpg.mvKey_S, callback=test_code)

with dpg.handler_registry():
    dpg.add_key_press_handler(
        key=dpg.mvKey_Q, callback=toggle_query_popup
    )  # Ctrl+Q for Query Editor

# Debug test function with inputs
# with dpg.handler_registry():
#     dpg.add_key_press_handler(key=dpg.mvKey_R, callback=lambda: print("a"))


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
        dpg.set_value("settings_date_picker", __get_current_date_struct())


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

    if len(df) > 1:
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

    # --- Add this block to update the header label with indicator ---
    for customer_id in df["customer_id"].unique():
        customer_name = df.loc[df["customer_id"] == customer_id, "customer_name"].iloc[
            0
        ]
        ongoing = False
        for item in dpg.get_all_items():
            if dpg.does_item_exist(item):
                tag_str = dpg.get_item_alias(item)
                if tag_str.startswith(f"checkbox_{customer_id}_"):
                    try:
                        if dpg.get_value(item):
                            ongoing = True
                            break
                    except Exception:
                        continue
        indicator = "* " if ongoing else ""
        try:
            dpg.configure_item(
                f"header_{customer_id}", label=f"{indicator}{customer_name}"
            )
        except Exception:
            pass  # Header might not exist yet


# Main Dear PyGui loop
was_minimized = False
while dpg.is_dearpygui_running():
    db.process_queue()
    periodic_update()
    dpg.render_dearpygui_frame()

    # Minimize detection logic here
    minimized = is_window_minimized(PROGRAM_NAME)
    if not minimized and was_minimized:
        __fix_headers()
    was_minimized = minimized

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
# alter table customers add column sort_order integer default 1
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

# alter table projects rename column git_id to git_id_old
# alter table projects add column git_id integer default 0
# update projects set git_id = gid_id_old where git_id_old <> 0
# alter projects drop column git_id_old

# alter table time rename column git_id to git_id_old
# alter table time add column git_id integer default 0
# update time set git_id = gid_id_old where git_id_old <> 0
# alter table time drop column git_id_old
