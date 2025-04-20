import dearpygui.dearpygui as dpg
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import time
import queue
import threading

import os
import sqlite3


###
# Constants
###
COMBO_WIDTH = 325
INDENT_1 = 15
INDENT_2 = 20

WARNING_RED = [255, 99, 71]
WARNING_GREEN = [34, 139, 34]

COMMIT = True
INIT = True

WIDTH = 500
HEIGHT = 800


TIME_ID = 0  # 0 = Day, 1 = Week, 2 = Month, 3 = Year, 4 = All-Time
TYPE_ID = 0  # 0 = Time, 1 = Bonus Wage
SELECTED_DATE = datetime.now().strftime("%Y-%m-%d")


###
# SQL-Backend logic
###
db_file = "data_test.db"
pre_run_log = []


def initialize_db(file_path: str) -> bool:
    global conn

    def add_dates(s_date, e_date) -> None:
        # Create a date range
        date_range = pd.date_range(start=s_date, end=e_date)

        # Build the date table
        date_table = pd.DataFrame(
            {
                "date_key": date_range.to_series().dt.strftime("%Y%m%d"),
                "date": date_range.to_series().dt.strftime("%Y-%m-%d"),
                "year": date_range.year,
                "month": date_range.month,
                "week": date_range.to_series().apply(
                    lambda x: x.isocalendar().week
                ),  # ISO week
                "day": date_range.day,
            }
        )

        date_table.to_sql("dates", conn, if_exists="append", index=False)

    if os.path.exists(file_path):
        pre_run_log.append(f"Database '{file_path}' exists. Opening...")
        conn = sqlite3.connect(file_path, check_same_thread=True)
        pre_run_log.append("Database opened successfully.")
        return conn
    else:
        pre_run_log.append(
            f"Database '{file_path}' does not exist. Creating a new one..."
        )
        conn = sqlite3.connect(file_path)

        ## Time
        conn.execute("""
        create table if not exists time (
            time_id integer primary key autoincrement,
            customer_id integer,
            customer_name str,
            project_id integer,
            project_name str,
            date_key int,
            start_time datetime,
            end_time datetime,
            total_time date,
            wage float,
            bonus float,
            cost float,
            user_bonus float,
            git_id int,
            comment str
        )
        """)
        pre_run_log.append("Table 'time' created successfully.")

        conn.execute("""
            create trigger if not exists trigger_time_after_update
            after update on time
            for each row
            begin
                update time
                set
                    total_time = (julianday(new.end_time) - julianday(new.start_time)) * 24,
                    cost = new.wage * ((julianday(new.end_time) - julianday(new.start_time)) * 24),
                    user_bonus = new.bonus * new.wage * ((julianday(new.end_time) - julianday(new.start_time)) * 24)
                where time_id = new.time_id;
            end;
        """)
        pre_run_log.append("Trigger 'trigger_time_after_update' created successfully.")

        ## Customers
        conn.execute("""
        create table if not exists customers (
            customer_id integer primary key autoincrement,
            customer_name text,
            start_date datetime,
            wage integer,
            valid_from datetime,
            valid_to datetime,
            is_current integer,
            inserted_at datetime,
            updated_at datetime
        )
        """)
        pre_run_log.append("Table 'customers' created successfully.")

        ## Projects
        conn.execute("""
        create table if not exists projects (
            project_id integer primary key autoincrement,
            customer_id integer,
            project_name str,
            git_id int,
            is_current bool
        )
        """)
        pre_run_log.append("Table 'projects' created successfully.")

        ## Bonus
        conn.execute("""
        create table if not exists bonus (
            bonus_id integer primary key autoincrement,
            bonus_percent float,
            start_date str,
            end_date str
        )
        """)
        pre_run_log.append("Table 'bonus' created successfully.")

        ## Dates
        conn.execute("""
            create table if not exists dates (
                 date_key integer unique
                ,date text unique
                ,year integer
                ,month integer
                ,week integer
                ,day integer
            )
        """)
        pre_run_log.append("Table 'dates' created successfully.")
        pre_run_log.append("Database initialized with empty tables.")

        try:
            add_dates(s_date="2020-01-01", e_date="2030-12-31")
            pre_run_log.append("Database auto-generated dates table.")
        except Exception as e:
            pre_run_log.append(f"Error reading from database: {e}")

        conn.commit()

    return conn


db_queue = queue.Queue()
conn = initialize_db(db_file)


## Modify Time Table
def insert_time_row(
    customer_id: int,
    project_id: int,
    git_id: int = None,
    comment: str = None,
) -> None:
    dt = datetime.now()
    now = dt.strftime("%Y-%m-%d %H:%M:%S")
    today = dt.strftime("%Y-%m-%d")

    r_queue = queue.Queue()
    queue_db_task(
        "get_customer_name_from_cid", {"customer_id": customer_id}, response=r_queue
    )
    customer_name = r_queue.get()

    queue_db_task(
        "get_project_name_from_pid", {"project_id": project_id}, response=r_queue
    )
    project_name = r_queue.get()

    if customer_id == "" or project_id == "":
        __log_message(
            f"Could not find project in db: {customer_name}, {project_name}",
            type="WARNING",
        )
        return

    date_key = int(dt.strftime("%Y%m%d"))

    sql_query = f"""
        select time_id, start_time, end_time
        from time 
        where customer_id = {customer_id} and project_id = {project_id} and end_time is null
        order by time_id desc
    """

    queue_db_task("get_df", {"query": sql_query, "params": {}}, response=r_queue)
    rows = r_queue.get()

    if len(rows) == 0:
        # Insert a new row with the current time as start_time
        w_queue = queue.Queue()
        b_queue = queue.Queue()
        queue_db_task("get_wage", {"customer_name": customer_name}, response=w_queue)
        wage = w_queue.get()
        queue_db_task("get_bonus", {"date": today}, response=b_queue)
        bonus = b_queue.get()

        sql_query = f"""
            insert into time (customer_id, customer_name, project_id, project_name, start_time, date_key, wage, bonus)
            values ({customer_id}, '{customer_name}', {project_id}, '{project_name}', '{now}', {date_key}, {wage}, {bonus})
        """
        queue_db_task("run_query", {"query": sql_query})
        __log_message(
            f"Starting timer for {customer_name}: {project_name}",
            type="INFO",
        )

    else:
        # Update the latest row with blank end_time
        last_row_id = rows.iloc[0]["time_id"]

        sql_query = f"""
            UPDATE time
            SET 
                end_time = '{now}',
                comment = '{comment}',
                git_id = {git_id}
            WHERE time_id = {last_row_id}
        """
        queue_db_task("run_query", {"query": sql_query})
        __log_message(
            f"Ending timer for {customer_name}: {project_name}",
            type="INFO",
        )

def insert_customer(
    customer_name: str, start_date: str, wage: int, valid_from: str = None
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not valid_from:
        valid_from = datetime.now().strftime("%Y-%m-%d")
        if valid_from > start_date:
            valid_from = start_date

    date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    day_before = date_obj - timedelta(days=1)
    valid_to = day_before.strftime("%Y-%m-%d")

    conn.execute(
        """
        update customers
        set 
             is_current = 0
            ,valid_to = ? 
            ,updated_at = ?
        where customer_name = ? AND is_current = 1
    """,
        (
            valid_to,
            now,
            customer_name,
        ),
    )

    conn.execute(
        "insert into customers (customer_name, start_date, wage, valid_from, valid_to, is_current, inserted_at, updated_at) values (?, ?, ?, ?, ?, 1, ?, ?)",
        (customer_name, start_date, wage, valid_from, None, now, None),
    )

    if COMMIT:
        conn.commit()


def update_customer(customer_name: str, new_customer_name: str, wage: int) -> None:
    conn.execute(
        """
        update customers
        set 
             customer_name = ?
            ,wage = ? 
        where customer_name = ?
    """,
        (
            new_customer_name,
            wage,
            customer_name,
        ),
    )

    conn.execute(
        """
        update time
        set 
             customer_name = ?
             ,wage = ? 
        where customer_name = ?
    """,
        (
            new_customer_name,
            wage,
            customer_name,
        ),
    )

    if COMMIT:
        conn.commit()


def remove_customer(customer_name: str) -> None:
    conn.execute(
        f"update customers set is_current = 0 where customer_name = '{customer_name}'"
    )
    if COMMIT:
        conn.commit()


## Modify Project Table
def insert_project(customer_name: str, project_name: str, git_id: int = None) -> None:
    customers = pd.read_sql(
        f"select * from customers where customer_name = '{customer_name}' and is_current = 1",
        conn,
    )
    customer_id = int(customers["customer_id"].iloc[0])

    projects = pd.read_sql(
        f"select * from projects where project_name = '{project_name}' and customer_id = '{customer_id}'",
        conn,
    )
    if len(projects[projects["is_current"] == 1]) > 0:
        return  # Project already exists in database!
    elif len(projects[projects["is_current"] == 0]) > 0:
        project_id = projects["project_id"].iloc[0]
        conn.execute(
            f"update projects set is_current = 1 where project_id = {project_id}"
        )
        # Project has been reactivated!
    else:
        conn.execute(
            "insert into projects (customer_id, project_name, is_current, git_id) values (?, ?, ?, ?)",
            (customer_id, project_name, 1, git_id),
        )
    if COMMIT:
        conn.commit()


def update_project(
    customer_name: str, project_name: str, new_project_name: str, new_git_id: int = None
) -> None:
    conn.execute(
        """
        update projects
        set 
              project_name = ?
             ,git_id = ?
        where project_name = ?
        and customer_id = (
            select customer_id
            from customers
            where customer_name = ?
            )
    """,
        (
            new_project_name,
            new_git_id,
            project_name,
            customer_name,
        ),
    )

    conn.execute(
        """
        update time
        set 
              project_name = ?
        where project_name = ?
        and customer_name = ?
    """,
        (
            new_project_name,
            project_name,
            customer_name,
        ),
    )

    if COMMIT:
        conn.commit()


def remove_project(customer_name: str, project_name: str) -> None:
    conn.execute(
        f"update projects set is_current = 0 where project_name = '{project_name}' and is_current = 1 and customer_id in (select customer_id from customers where customer_name = '{customer_name}' and is_current = 1)"
    )

    if COMMIT:
        conn.commit()


## Modify Bonus Table
def insert_bonus(start_date: str, amount: float) -> None:
    day_before_start_date = (
        datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    conn.execute(
        f"update bonus set end_date = '{day_before_start_date}' where end_date is Null"
    )

    conn.execute(
        "insert into bonus (start_date, bonus_percent) values (?, ?)",
        (start_date, round(amount, 3)),
    )
    if COMMIT:
        conn.commit()


dpg.create_context()

## Image Input
width, height, channels, data = dpg.load_image("icon_calendar.png")
with dpg.texture_registry():
    icon_calendar = dpg.add_static_texture(width, height, data)

# Temp df, all code should read directly from db!
# df = pd.read_sql(
#     "select c.customer_id, c.customer_name, p.project_id, p.project_name, 0 as initial_state, '0 h' as initial_text, c.wage from projects p left join customers c on c.customer_id = p.customer_id and c.is_current = 1 where p.is_current = 1 ",
#     conn,
# )
input_focused = False


###
# Queue
###
def process_db_queue():
    while not db_queue.empty():
        task = db_queue.get()
        action = task["action"]
        data = task["data"]
        response = task["response"]
        if action == "insert_customer":
            insert_customer(
                data["customer_name"], data["start_date"], int(data["wage"])
            )
        elif action == "update_customer":
            update_customer(
                data["customer_name"], data["new_customer_name"], int(data["wage"])
            )
        elif action == "remove_customer":
            remove_customer(data["customer_name"])
        elif action == "insert_project":
            insert_project(data["customer_name"], data["project_name"], data["git_id"])
        elif action == "update_project":
            update_project(
                data["customer_name"],
                data["project_name"],
                data["new_project_name"],
                data["new_git_id"],
            )
        elif action == "delete_project":
            remove_project(data["customer_name"], data["project_name"])

        elif action == "insert_bonus":
            insert_bonus(data["start_date"], data["amount"])

        elif action == "get_wage":
            result = pd.read_sql(
                f"select wage from customers where customer_name = '{data['customer_name']}' and is_current = 1",
                conn,
            )
            result = _get_value_from_df(result, data_type="int")
        elif action == "get_bonus":
            result = pd.read_sql(
                f"select bonus_percent from bonus where '{data['date']}' between start_date and ifnull(end_date, '2099-12-31')",
                conn,
            )
            result = _get_value_from_df(result, data_type="float")
        elif action == "get_customer_name_from_cid":
            result = pd.read_sql(
                f"select customer_name from customers where customer_id = '{data['customer_id']}'",
                conn,
            )
            result = _get_value_from_df(result, data_type="str")
        elif action == "get_project_name_from_pid":
            result = pd.read_sql(
                f"select project_name from projects where project_id = '{data['project_id']}'",
                conn,
            )
            result = _get_value_from_df(result, data_type="str")
        elif action == "get_active_customers":
            result = (
                pd.read_sql(
                    "select distinct c.customer_name from projects p left join customers c on c.customer_id = p.customer_id and p.is_current = 1 where c.is_current = 1",
                    conn,
                )["customer_name"]
                .unique()
                .tolist()
            )
        elif action == "get_customer_names":
            result = (
                pd.read_sql(
                    "select customer_name from customers where is_current = 1", conn
                )["customer_name"]
                .unique()
                .tolist()
            )
        elif action == "get_customer_ui_list":
            result = pd.read_sql(
                "select c.customer_id, c.customer_name, p.project_id, p.project_name, 0 as initial_state, '0 h' as initial_text, c.wage from projects p left join customers c on c.customer_id = p.customer_id and c.is_current = 1 where p.is_current = 1",
                conn,
            )
        elif action == "get_project_names":
            result = (
                pd.read_sql(
                    f"select p.project_name from projects p left join customers c on c.customer_id = p.customer_id where c.customer_name = '{data['customer_name']}' and p.is_current = 1",
                    conn,
                )["project_name"]
                .unique()
                .tolist()
            )

        elif action == "run_query":
            try:
                result = pd.read_sql(data["query"], conn)
            except Exception as e:
                result = e
                __log_message(
                    f"Select statement failed: {data['query']} \nError: {e}",
                    type="WARNING",
                )
                __log_message(
                    f"Select statement failed: {data['query']} \nError: {e}",
                    type="WARNING",
                )



def queue_db_task(action: str, data: dict, response=None) -> None:
    db_queue.put(
        {
            "action": action,
            "data": data,
            "response": response,  # Optional
        }
    )


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


def populate_pre_log():
    for line in pre_run_log:
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


def __update_dropdown(tag: str, c_name: str = None) -> None:
    if tag == "customer_dropdown":
        r_queue = queue.Queue()
        queue_db_task("get_customer_names", {}, response=r_queue)
        customers = r_queue.get()
        dpg.configure_item("customer_update_name_dropdown", items=customers)
        dpg.configure_item("customer_delete_name_dropdown", items=customers)
        dpg.configure_item("project_add_customer_name_dropdown", items=customers)

        queue_db_task("get_active_customers", {}, response=r_queue)
        customers = r_queue.get()
        dpg.configure_item("project_update_customer_name_dropdown", items=customers)
        dpg.configure_item("project_delete_customer_name_dropdown", items=customers)

    elif tag == "project_update_project_name_dropdown":
        if INIT:  # Ensure no dead-lock during setup
            return

        customer_name = dpg.get_value("project_update_customer_name_dropdown")

        r_queue = queue.Queue()
        queue_db_task(
            "get_project_names", {"customer_name": customer_name}, response=r_queue
        )
        projects = r_queue.get()
        dpg.configure_item(tag, items=projects)
    elif tag == "project_delete_project_name_dropdown":
        if INIT:  # Ensure no dead-lock during setup
            return

        customer_name = dpg.get_value("project_delete_customer_name_dropdown")
        r_queue = queue.Queue()
        queue_db_task(
            "get_project_names", {"customer_name": customer_name}, response=r_queue
        )
        projects = r_queue.get()
        dpg.configure_item(tag, items=projects)


def __update_text_input(tag: str):
    if tag == "customer_update_name_dropdown":
        cur_val = dpg.get_value(tag)
        dpg.set_value("customer_update_customer_name_input", cur_val)

        r_queue = queue.Queue()
        queue_db_task("get_wage", {"customer_name": cur_val}, response=r_queue)
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
        queue_db_task("get_df", {"query": query}, response=r_queue)
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
    queue_db_task("get_df", {"query": "select * from dates"}, response=d_queue)
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

    dpg.delete_item("customer_ui_section", children_only=True)

    __update_dropdown("customer_dropdown")

    r_queue = queue.Queue()
    queue_db_task(
        "get_customer_ui_list",
        {"start_date": start_date, "end_date": end_date, "data_type": sel_type},
        response=r_queue,
    )
    df = r_queue.get()

    for customer_id in df["customer_id"].unique():
        customer_name = df.loc[df["customer_id"] == customer_id, "customer_name"].iloc[
            0
        ]

        # One header per customer inside the "Customers" section
        header_id = dpg.add_collapsing_header(
            label=customer_name,
            default_open=True,
            indent=10,
            parent="customer_ui_section",
        )

        dpg.add_text("", parent=header_id, tag=f"total_{customer_id}")

        db_queue = queue.Queue()
        for _, row in df[df["customer_id"] == customer_id].iterrows():
            project_id = row["project_id"]
            project_name = row["project_name"]

            sql_query = f"select * from time where customer_id = {customer_id} and project_id = {project_id} and end_time is null"
            queue_db_task(
                "get_df",
                {"query": sql_query, "meta_data": "render_customer_project_ui"},
                response=db_queue,
            )
            counts = db_queue.get()
            initial_state = True if len(counts) > 0 else False

            group_id = dpg.add_group(horizontal=True, parent=header_id)

            dpg.add_checkbox(
                label=f"{project_name:<35}",
                callback=project_button_callback,
                user_data=(customer_id, project_id),
                default_value=initial_state,
                parent=group_id,
            )

            dpg.add_text("", tag=f"time_{customer_id}_{project_id}", parent=group_id)

    run_update_ui_task()


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
    customer_id, project_id = user_data

    if app_data:
        insert_time_row(customer_id, project_id)
    else:
        show_project_popup(sender, app_data, customer_id, project_id)

    run_update_ui_task()


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
            width=WIDTH / 2,
            height=HEIGHT / 4,
        ):
            dpg.add_text("Work Comments")
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

    insert_time_row(customer_id, project_id, git_id, comment)
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


def handle_query_input():
    if input_focused:
        query_text = dpg.get_value("query_input")

        r_queue = queue.Queue()
        queue_db_task("run_query", {"query": query_text}, response=r_queue)
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
        arr = df.to_numpy()

        dpg.delete_item("data_table", children_only=True)

        for column in df.columns:
            dpg.add_table_column(parent="data_table", label=column)

        for i in range(df.shape[0]):
            with dpg.table_row(parent="data_table"):
                for j in range(df.shape[1]):
                    dpg.add_text(f"{arr[i, j]}")


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
    # Update Project
    dpg.set_value("project_update_customer_name_dropdown", "")
    dpg.set_value("project_update_project_name_dropdown", "")
    dpg.set_value("project_update_name_input", "")
    # Remove Project
    dpg.set_value("project_delete_customer_name_dropdown", "")
    dpg.set_value("project_delete_project_name_dropdown", "")

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
        queue_db_task(
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
    queue_db_task(
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
    queue_db_task("remove_customer", {"customer_name": customer_name})
    __update_dropdown("customer_dropdown")
    __post_user_input()
    __log_message(
        f"Customer {customer_name} disabled in the DB",
        type="INFO",
    )


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
    queue_db_task(
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
    queue_db_task(
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
    queue_db_task(
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
    queue_db_task("insert_bonus", {"amount": amount, "start_date": start_date})
    __post_user_input()
    __log_message(
        f"Bonus percent {amount} starting on {start_date} added to the DB",
        type="INFO",
    )


###
# UI
###
with dpg.window(label="Work Timer v2", width=WIDTH, height=HEIGHT):
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
                        label="Done", callback=lambda: set_start_date("customer_add")
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
            label="Project", default_open=False, indent=INDENT_1
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
                dpg.add_input_text(label="Project Name", tag="project_add_name_input")
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
                dpg.add_input_text(label="New Name", tag="project_update_name_input")

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
            label="Bonuses", default_open=False, indent=INDENT_1
        ):
            with dpg.collapsing_header(
                label="Add Bonus", default_open=False, indent=INDENT_2
            ):
                dpg.add_input_float(label="Bonus Amount", tag="bonus_add_amount_input")
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
            available_tables = ["time", "customers", "projects", "bonus", "dates"]
            with dpg.group(horizontal=True):
                dpg.add_text("Available tables:")
                for table in available_tables:
                    dpg.add_button(
                        label=table,
                        callback=lambda t=str(table): __autoset_query_window(t),
                    )

            dpg.add_spacer(width=10)
            dpg.add_text("Enter Query:")
            sql_input = "select * from time"
            dpg.add_input_text(
                multiline=True,
                width=WIDTH - 30,
                height=HEIGHT / 6,
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
        with dpg.group(tag="query_output_group"):
            dpg.add_text("Tabular Data:")

            with dpg.table(tag="data_table", resizable=True, width=WIDTH - 30):
                pass  # Blank for dynamic columns

    with dpg.handler_registry():
        dpg.add_key_press_handler(key=dpg.mvKey_F5, callback=handle_query_input)

    with dpg.collapsing_header(
        label="Customers", default_open=True, tag="customers_section"
    ):
        with dpg.child_window(
            tag="customer_ui_section", autosize_x=True, autosize_y=True, border=False
        ):
            pass  # Placeholder for dynamic content

    # Logg Section
    with dpg.collapsing_header(label="Logs", default_open=False):
        dpg.add_input_text(
            tag="log_box", multiline=True, readonly=True, width=WIDTH - 30, height=200
        )


frame = dpg.create_viewport(
    title="Work Timer v2",
    width=WIDTH + 15,
    height=HEIGHT + 50,
    small_icon="favicon.ico",
    large_icon="favicon.ico",
)
dpg.setup_dearpygui()
dpg.show_viewport()

dpg.set_frame_callback(1, render_customer_project_ui)
dpg.set_frame_callback(2, populate_pre_log)
INIT = False


last_update_time = time.time()


def periodic_update():
    """Function to periodically queue the update task."""
    global last_update_time
    current_time = time.time()
    if current_time - last_update_time >= 60:
        threading.Thread(target=run_update_ui_task, daemon=True).start()
        last_update_time = current_time


def run_update_ui_task():
    """Run the update UI task in a separate thread."""
    start_date, end_date, sel_type = __get_user_input()

    r_queue = queue.Queue()
    queue_db_task(
        "get_customer_ui_list",
        {"start_date": start_date, "end_date": end_date, "data_type": sel_type},
        response=r_queue,
    )
    df = r_queue.get()
    print(df)

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
    process_db_queue()
    periodic_update()
    dpg.render_dearpygui_frame()

dpg.destroy_context()


###############################
### update old db to new db ###
###############################

# alter table time add git_id str, user_bonus float
# alter table dates drop column iso_year
# alter table projects add git_id int

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
