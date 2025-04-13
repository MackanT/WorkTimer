import os
from typing import Literal, Any
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import re
from functools import partial

import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk, messagebox, simpledialog


# File path for the SQLite database
db_file = "data.db"


def __get_customer_id(customer_name: str, date: str) -> int:
    query = """
        SELECT customer_id 
        FROM customers 
        WHERE customer_name = ? 
        AND ? BETWEEN valid_from AND COALESCE(valid_to, '2099-12-31')
    """
    try:
        customer_id_df = pd.read_sql(query, conn, params=(customer_name, date))
        if customer_id_df.empty:
            return -1
        return int(customer_id_df.iloc[0, 0])
    except Exception as e:
        print(f"Error fetching customer ID: {e}")
        return -1


def __get_project_id(project_name: str) -> int:
    query = "SELECT project_id FROM projects WHERE project_name = ?"
    try:
        project_id_df = pd.read_sql(query, conn, params=(project_name,))
        if project_id_df.empty:
            return -1
        return int(project_id_df.iloc[0, 0])
    except Exception as e:
        print(f"Error fetching project ID: {e}")
        return -1


def initialize_db(file_path: str) -> bool:
    global conn

    def add_dates() -> None:
        start_date = "2020-01-01"
        end_date = "2030-12-31"

        # Create a date range
        date_range = pd.date_range(start=start_date, end=end_date)

        # Build the date table
        date_table = pd.DataFrame(
            {
                "date_key": date_range.to_series().dt.strftime("%Y%m%d"),
                "date": date_range.to_series().dt.strftime("%Y-%m-%d"),
                "year": date_range.year,  # Gregorian year
                "iso_year": date_range.to_series().apply(
                    lambda x: x.isocalendar().year
                ),  # ISO year
                "month": date_range.month,  # Month
                "week": date_range.to_series().apply(
                    lambda x: x.isocalendar().week
                ),  # ISO week
                "day": date_range.day,  # Day of the month
            }
        )

        date_table.to_sql("dates", conn, if_exists="append", index=False)

    if os.path.exists(file_path):
        print(f"File '{file_path}' exists. Opening...")
        conn = sqlite3.connect(file_path)
        print("Database opened successfully.")
        return conn
    else:
        print(f"File '{file_path}' does not exist. Creating a new one...")
        conn = sqlite3.connect(file_path)

        ## Time
        conn.execute("""
        create table if not exists time (
            time_id integer primary key autoincrement,
            customer_id integer,
            customer_name str,
            project_id integer,
            project_name str,
            start_time datetime,
            end_time datetime,
            comment str,
            date_key int,
            total_time date,
            cost float,
            bonus float,
            wage float
        )
        """)
        print("Table 'time' created successfully.")

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
        print("Table 'customers' created successfully.")

        ## Projects
        conn.execute("""
        create table if not exists projects (
            project_id integer primary key autoincrement,
            customer_id integer,
            project_name str,
            is_current bool
        )
        """)
        print("Table 'projects' created successfully.")

        ## Bonus
        conn.execute("""
        create table if not exists bonus (
            bonus_id integer primary key autoincrement,
            bonus_percent float,
            start_date str,
            end_date str
        )
        """)
        print("Table 'bonus' created successfully.")

        ## Dates
        conn.execute("""
            create table if not exists dates (
                 date_key integer unique
                ,date text unique
                ,year integer
                ,iso_year integer
                ,month integer
                ,week integer
                ,day integer
            )
        """)
        print("Table 'dates' created successfully.")

        print("Database initialized with empty tables.")

        try:
            add_dates()
        except Exception as e:
            print(f"Error reading from database: {e}")

        conn.commit()

    return conn


# Insert into tables
def insert_customer(
    customer_name: str, start_date: str, wage: int, valid_from: str
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
    # conn.commit()


def insert_time_row(
    customer_name: str,
    project_name: str,
    date: str = None,
    time: str = None,
    comment: str = None,
    commit: bool = True,
) -> None:
    # If adding historic data
    if date and time:
        now = f"{date} {time}"
        today = date
    else:
        dt = datetime.now()
        now = dt.strftime("%Y-%m-%d %H:%M:%S")
        today = dt.strftime("%Y-%m-%d")

    customer_id = __get_customer_id(customer_name, today)
    project_id = __get_project_id(project_name)
    if customer_id == -1 or project_id == -1:
        print("Could not find corresponding data!")
        return

    date_key = int(
        pd.read_sql(f"select * from dates where date = '{today}'", conn).iloc[0, 0]
    )

    cursor = conn.execute(
        """
        select time_id, start_time, end_time
        from time 
        where customer_id = ? and project_id = ? and date(start_time) = ?
        order by time_id desc
    """,
        (customer_id, project_id, today),
    )
    rows = cursor.fetchall()

    if not rows or all(
        row[2] is not None for row in rows
    ):  # No rows or all rows have end_time filled
        # Insert a new row with the current time as start_time
        conn.execute(
            """
            INSERT INTO time (customer_id, customer_name, project_id, project_name, start_time, date_key)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (customer_id, customer_name, project_id, project_name, now, date_key),
        )

    else:
        # Update the latest row with blank end_time
        last_row_id = rows[0][0]
        cost_df = pd.read_sql(
            f"SELECT wage FROM customers where customer_id = {customer_id}", conn
        )
        if cost_df.empty:
            cost = 0
        else:
            cost = int(cost_df.iloc[0, 0])

        bonus_df = pd.read_sql(
            f"SELECT bonus_percent FROM bonus where '{today}' between start_date and coalesce(end_date, '2099-12-31')",
            conn,
        )
        if bonus_df.empty:
            bonus = 0.0
        else:
            bonus = float(bonus_df.iloc[0, 0])

        conn.execute(
            """
            UPDATE time
            SET 
                end_time = :end_time,
                total_time = (JULIANDAY(:end_time) - JULIANDAY(start_time)) * 24,
                cost = (JULIANDAY(:end_time) - JULIANDAY(start_time)) * 24 * :cost_rate,
                bonus = :bonus,
                wage = (JULIANDAY(:end_time) - JULIANDAY(start_time)) * 24 * :cost_rate * :bonus_rate,
                comment = :comment
            WHERE time_id = :time_id
        """,
            {
                "end_time": now,
                "cost_rate": cost,
                "bonus": bonus,
                "bonus_rate": bonus,
                "time_id": last_row_id,
                "comment": comment,
            },
        )

    if commit:
        conn.commit()


def insert_project(
    project_name: str, customer_name: str, is_current: bool, commit: bool = True
) -> None:
    customer_id = __get_customer_id(customer_name, datetime.now().strftime("%Y-%m-%d"))
    conn.execute(
        "insert into projects (customer_id, project_name, is_current) values (?, ?, ?)",
        (customer_id, project_name, is_current),
    )
    if commit:
        conn.commit()


def insert_bonus(
    bonus_percent: float,
    start_date: str,
    end_date: str | None = None,
    commit: bool = True,
) -> None:
    if not end_date:
        date_obj = datetime.strptime(start_date, "%Y%m%d")
        day_before = date_obj - timedelta(days=1)
        new_end_date = day_before.strftime("%Y-%m-%d")
        conn.execute(
            f"update bonus set end_date = '{new_end_date}' where end_date is Null"
        )
        conn.commit()
    if len(start_date) == 8:
        start_date = __format_date(start_date)

    conn.execute(
        "insert into bonus (bonus_percent, start_date, end_date) values (?, ?, ?)",
        (bonus_percent, start_date, end_date),
    )
    if commit:
        conn.commit()


def insert_historic_time(file_name: str, customer_name: str, project_name: str) -> None:
    """Runs through files from old format and finds corresponding customer id for specific date. Stores times in time-table"""
    with open(file_name, "r") as f:
        content = f.readlines()

    pattern = r"^[0-1]{1}\d{4}-\d{2}-\d{2}.\d{2}:\d{2}:\d{2}\n$"

    for line in content:
        if not re.match(pattern, line):
            continue
        cleaned = line[1:-1]
        date, time = cleaned.split(" ")
        insert_time_row(customer_name, project_name, date, time, commit=False)


# Insert into tables from UI
def __add_customer_project(data: dict) -> tuple[bool, str]:
    p_name = data["Project Name"]
    c_name = data["Customer Name"]

    customers = pd.read_sql(
        f"select * from customers where customer_name = '{c_name}'", conn
    )
    if len(customers) == 0:  # Add customer
        return (False, "Customer does not exist in the database!")

    customer_id = customers["customer_id"].iloc[0]

    projects = pd.read_sql(
        f"select * from projects where project_name = '{p_name}' and customer_id = '{customer_id}'",
        conn,
    )
    if len(projects[projects["is_current"] == 1]) > 0:
        return (False, "Project already exists in database!")

    elif len(projects[projects["is_current"] == 0]) > 0:
        project_id = projects["project_id"].iloc[0]
        conn.execute(
            f"update projects set is_current = 1 where project_id = {project_id}"
        )
        return (True, "Project has been reactivated!")
    else:
        insert_project(p_name, c_name, True)

    return (True, "Successfully added new Project")


def __disable_customer_project(p_id: int) -> tuple[bool, str]:
    conn.execute(f"update projects set is_current = 0 where project_id = {p_id}")
    conn.commit()
    return (True, "Project has been deactivated!")


def __add_customer(data: dict) -> tuple[bool, str]:
    c_name = data["Customer Name"]
    s_date = data["Start Date"]
    s_date = f"{s_date[:4]}-{s_date[4:6]}-{s_date[-2:]}"
    wage = int(data["Wage"])

    customers = pd.read_sql(
        f"select * from customers where customer_name = '{c_name}'", conn
    )
    if len(customers) == 0:  # New customer
        insert_customer(c_name, s_date, wage, s_date)
        return (True, f"Customer {c_name} added to the database!")

    customer_id = customers["customer_id"].iloc[0]

    if len(customers[customers["is_current"] == 1]) > 0:
        insert_customer(c_name, s_date, wage, s_date)
        return (
            True,
            f"Customer {c_name} already exists in the database, updating wage!",
        )

    elif len(customers[customers["is_current"] == 0]) > 0:
        conn.execute(
            f"update customers set is_current = 1 where customer_id = {customer_id}"
        )
        conn.commit()
        return (True, "Customer has been reactivated!")
    else:
        return (False, "Unknown operation!")


def __disable_customer(c_name: str) -> tuple[bool, str]:
    conn.execute(
        f"update customers set is_current = 0 where customer_name = '{c_name}'"
    )
    conn.commit()
    return (True, f"Customer {c_name} has been deactivated!")


def __add_bonus(data: dict) -> tuple[bool, str]:
    amount = float(data["Bonus Percent"])
    date = data["Start Date"]
    insert_bonus(amount, date)
    return (True, f"Bonus percent {amount} added to the database!")


# Get time values
def __get_value(customer_name: str, project_name: str, date_key: int) -> float:
    date_data = pd.read_sql(
        f"select * from dates where date_key = '{date_key}'", conn
    ).iloc[0]

    query = """
        select 
             t.start_time
            ,t.end_time
            ,c.wage
            ,b.bonus_percent
            ,d.date_key
            ,d.year
            ,d.iso_year
            ,d.month
            ,d.week
            ,d.day
        from time t
        left join dates d on d.date_key = t.date_key
        left join customers c on c.customer_id = t.customer_id
        left join bonus b on date(t.start_time) between b.start_date and coalesce(b.end_date, '2099-12-31')
        where
            t.customer_name = ? 
            and t.project_name = ? 
    """
    params = (customer_name, project_name)
    data = pd.read_sql(query, conn, params=params)

    data.loc[
        (data["end_time"].isnull()) & (data["date_key"] == date_key), "end_time"
    ] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data["total_time"] = pd.to_datetime(data["end_time"]) - pd.to_datetime(
        data["start_time"]
    )
    data["total_hours"] = data["total_time"].dt.total_seconds() / 3600
    data["payout"] = data["total_hours"] * data["wage"] * data["bonus_percent"]

    if data.empty:
        return 0

    if data_format in [0, 1]:
        sum_column = "total_hours"
    elif data_format in [2, 3]:
        sum_column = "payout"

    ## Return todays value
    if time_index == 0:  # Today
        val = data[data["date_key"] == date_key][sum_column].sum()
    elif time_index == 1:  # Week
        iso_year = date_data["iso_year"]
        iso_week = date_data["week"]
        val = data[(data["iso_year"] == iso_year) & (data["week"] == iso_week)][
            sum_column
        ].sum()
    elif time_index == 2:  # Month
        year = date_data["year"]
        month = date_data["month"]
        val = data[(data["year"] == year) & (data["month"] == month)][sum_column].sum()
    elif time_index == 3:  # Year
        year = date_data["year"]
        val = data[data["year"] == year][sum_column].sum()
    else:
        val = data[sum_column].sum()

    return val


def __update_user_input_date(*args):
    global user_input_date, date_input
    user_input_date = int(date_input.get())
    __update_value()


def __update_value() -> None:
    for obj in projects:
        c_name, p_name, label = obj
        time = __get_value(c_name, p_name, user_input_date)
        formatted_value = __format_value(time)
        label.config(text=formatted_value)


def __update_project(c_name: str, p_name: str, button: tk.Button) -> None:
    current_color = button.cget("bg")
    if current_color == __get_color("green"):
        comment = simpledialog.askstring("Comment", "What work was conducted?")
    else:
        comment = ""
    if comment is None:
        return
    insert_time_row(c_name, p_name, comment=comment)
    color = (
        __get_color("green")
        if current_color == __get_color("red")
        else __get_color("red")
    )
    button.config(bg=color)


### SQL ###
def __populate_sql_output(sql_output: ttk.Treeview, data: pd.DataFrame) -> None:
    """Populate Treeview with DataFrame content."""
    # Clear any existing data
    for row in sql_output.get_children():
        sql_output.delete(row)

    # Insert new data
    sql_output["columns"] = list(data.columns)
    sql_output["show"] = "headings"  # Hide default empty column

    # Add column headers
    for column in data.columns:
        sql_output.heading(column, text=column)
        sql_output.column(column, width=100, anchor="center")

    # Add rows
    for _, row in data.iterrows():
        sql_output.insert("", "end", values=list(row))

    sql_output.place(relx=0.01, rely=0.01, width=1160, height=300)


def __run_sql(
    event, frame: tk.Toplevel, sql_input: tk.Entry, sql_output: ttk.Treeview
) -> None:
    sql_code = sql_input.get()

    override = False
    if "delete" in sql_code or "update" in sql_code:
        frame.grab_set()
        result = messagebox.askyesno(
            "Confirm",
            "Running the SQL-command will make changes to the data do you want that?",
        )
        frame.grab_release()
        if result:
            override = True
        else:
            return

    try:
        if override:
            conn.execute(sql_code)
            conn.commit()
            messagebox.showinfo(
                "SQL-Command Successful", f"SQL command:\n\n{sql_code} ran successfully"
            )
        else:
            data = pd.read_sql(sql_code, conn)
            __populate_sql_output(sql_output, data)
            frame.geometry(f"{frame.winfo_width()}x{395}")

    except Exception as e:
        print(f"Error running sql-code {sql_code}: {e}")


def __update_value_id(val: int) -> None:
    data = pd.read_sql(f"select * from time where time_id = {val}", conn)

    if len(data) == 0:
        return

    start_time = data["start_time"].iloc[0][0:10]
    end_time = data["end_time"].iloc[0]
    c_id = data["customer_id"].iloc[0]

    cost_df = pd.read_sql(
        f"SELECT wage FROM customers where customer_id = {c_id}", conn
    )
    if cost_df.empty:
        cost = 0
    else:
        cost = int(cost_df.iloc[0, 0])

    bonus_df = pd.read_sql(
        f"SELECT bonus_percent FROM bonus where '{start_time}' between start_date and coalesce(end_date, '2099-12-31')",
        conn,
    )
    if bonus_df.empty:
        bonus = 0.0
    else:
        bonus = float(bonus_df.iloc[0, 0])

    conn.execute(
        """
        UPDATE time
        SET 
            total_time = (JULIANDAY(:end_time) - JULIANDAY(start_time)) * 24,
            cost = (JULIANDAY(:end_time) - JULIANDAY(start_time)) * 24 * :cost_rate,
            bonus = :bonus,
            wage = (JULIANDAY(:end_time) - JULIANDAY(start_time)) * 24 * :cost_rate * :bonus_rate
        WHERE time_id = :time_id
    """,
        {
            "end_time": end_time,
            "cost_rate": cost,
            "bonus": bonus,
            "bonus_rate": bonus,
            "time_id": val,
        },
    )
    conn.commit()


### Utilities ###
def __get_font(size: int, bold: bool = False):
    if bold:
        return tkFont.Font(family="Bahnscrift", size=size, weight="bold")
    else:
        return tkFont.Font(family="Bahnscrift", size=size)


def __get_color(col: str) -> str:
    return COLS[col]


def __format_date_key(date: str) -> str:
    return date.strftime("%Y%m%d")


def __format_date(date: str) -> str:
    a = datetime.strptime(date, "%Y%m%d")
    return a.strftime("%Y-%m-%d")


def __format_value(value: float) -> str:
    formatted_value = "arst"
    if data_format == 0:
        hours = int(value)
        minutes = int((value - hours) * 60)
        formatted_value = f"{hours} h {minutes} min"
    elif data_format == 1:
        formatted_value = f"{round(value, 2)} h"
    elif data_format == 2:
        formatted_value = f"{round(value, 0)} SEK"

    return formatted_value


def __get_active_projects() -> pd.DataFrame:
    projects = pd.read_sql(
        "select c.customer_name, c.customer_id, p.project_name, p.project_id from projects p left join customers c on c.customer_id = p.customer_id where p.is_current = 1 and c.is_current = 1",
        conn,
    )
    return projects.sort_values(by="customer_name")


def __entry_int_check(var: tk.Entry, p: int, *args):
    value = var.get()

    # Ignore validation if the value is the placeholder
    if value == p:
        return

    if not value.isdigit():
        var.set("".join(filter(str.isdigit, value)))


def __entry_float_check(var: tk.Entry, p: str, *args):
    value = var.get()

    # Ignore validation if the value is the placeholder
    if value == p:
        return

    # Allow empty input to clear the field
    if value == "":
        return

    # Check if the value is a valid float or can potentially be a float
    try:
        float(value)
    except ValueError:
        # If not valid, filter the value to keep only float-compatible characters
        valid_chars = "-0123456789."
        # Allow only the first `-` at the start and a single `.`
        filtered_value = "".join(
            c
            for i, c in enumerate(value)
            if c in valid_chars
            and (c != "-" or i == 0)
            and (c != "." or value[:i].count(".") == 0)
        )
        var.set(filtered_value)


def __entry_date_check(var: tk.Entry, p: str, *args):
    value = var.get()

    # Ignore validation if the value is the placeholder
    if value == p:
        return

    # Remove any non-digit characters
    if not value.isdigit():
        var.set("".join(filter(str.isdigit, value)))
        return

    # Limit the length to 8 characters
    if len(value) > 8:
        var.set(value[:8])
        return

    # If length is 8, validate the date
    if len(value) == 8:
        try:
            datetime.strptime(value, "%Y%m%d")  # Validate using datetime
        except ValueError:
            var.set(value[:-1])  # Remove last character if invalid


def __entry_on_focus_in(event, p: str):
    entry = event.widget
    if entry.get() == p:
        entry.delete(0, tk.END)  # Remove placeholder text
        entry.config(fg="black")  # Change text color to black


def __entry_on_focus_out(event, p: str):
    entry = event.widget
    if entry.get() == "":  # If entry is empty, reinsert placeholder
        entry.insert(0, p)
        entry.config(fg="gray")  # Change text color back to gray


def __attempt_save_user_input(
    frame: tk.Toplevel, add_function, d_dict: dict = None, entity=None
):
    data = {}

    for name, dd in d_dict.items():
        text = dd["entry"].get()
        if text != name:
            data[name] = text
        else:
            data[name] = None

    # Call the provided add function
    success, msg = add_function(data)

    if success:
        messagebox.showinfo("Success", msg)
        frame.destroy()
        __update_ui()
    else:
        messagebox.showwarning("Failure", msg)


def __attempt_remove_user_input(frame: tk.Toplevel, func, entity, d_dict: dict = None):
    success = False
    msg = ""
    if isinstance(entity, ttk.Combobox):
        value = entity.get()

        if not d_dict:
            for c_name in entity.cget("values"):
                if value == c_name:
                    success, msg = func(c_name)
                    break
        else:
            p_id = d_dict[entity.get()]["p_id"]
            success, msg = func(p_id)

        if success:
            messagebox.showinfo("Success", msg)
            frame.destroy()
            __update_ui()
        else:
            messagebox.showwarning("Failure", msg)


### UI ###
def __create_popup(
    frame: tk.Toplevel, title: str, text: str, width: int = 100, height: int = None
) -> tk.Toplevel:
    if height:
        popup_window = tk.Toplevel(
            frame, bg=__get_color("beige"), width=width, height=height
        )
    else:
        popup_window = tk.Toplevel(frame, bg=__get_color("beige"), width=width)
    popup_window.title(title)

    popup_window.resizable(False, False)

    # __add_label(
    #     popup_window,
    #     text=text,
    # )
    label = __add_label(popup_window, text, font_size=14)
    label.pack(padx=10, pady=10)

    return popup_window


def __add_combobox(frame: tk.Toplevel, entries: list) -> ttk.Combobox:
    combobox = ttk.Combobox(frame, state="readonly", width=20, font=__get_font(10))
    combobox.pack(padx=10, pady=10)
    combobox.focus()
    combobox["values"] = entries

    return combobox


def __add_entry(
    frame: tk.Toplevel,
    text_var: tk.StringVar,
    text: str,
    width: int = 16,
    pack: bool = True,
) -> tk.Entry:
    entry = tk.Entry(
        frame,
        fg="gray",
        textvariable=text_var if text_var else None,
        width=width,
        font=__get_font(10),
    )
    entry.config({"background": __get_color("background")})
    entry.insert(0, text)
    entry.bind("<FocusIn>", lambda event, p=text: __entry_on_focus_in(event, p))
    entry.bind("<FocusOut>", lambda event, p=text: __entry_on_focus_out(event, p))
    if pack:
        entry.pack(padx=10, pady=10)

    return entry


def __add_entries(
    frame: tk.Toplevel,
    entry_configs: list[dict[Literal["label", "textvariable", "trace_function"], Any]],
) -> dict:
    d_dict = {}
    for config in entry_configs:
        t = config["label"]
        text_var = config["textvariable"]
        if text_var and config["trace_function"]:
            text_var.trace_add("write", partial(config["trace_function"], text_var, t))
        entry = __add_entry(frame, text_var, t)
        d_dict[t] = {"entry": entry}

    return d_dict


def __add_label(
    frame: tk.Toplevel,
    text: str,
    bg: str = None,
    fg: str = None,
    font_size: int = 13,
    bold: bool = True,
    width: int = 18,
    height: int = 1,
    anchor: Literal["w", "e", "s", "n"] = tk.W,
) -> tk.Label:
    if not bg:
        bg = "beige"
    if not fg:
        fg = "teal"

    label = tk.Label(
        frame,
        text=text,
        bg=__get_color(bg),
        fg=__get_color(fg),
        font=__get_font(font_size, bold),
        width=width,
        height=height,
        anchor=anchor,
    )
    return label


def __add_button(
    frame: tk.Toplevel,
    text: str,
    cmd,
    side: str = "right",
    padx: int = 10,
    pady: int = 10,
    width: int = 8,
    height: int = 1,
    font_size: int = 10,
    bold: bool = True,
    bg: str = None,
    fg: str = None,
    pack: bool = True,
) -> tk.Button:
    if not bg:
        bg = "green"
    if not fg:
        fg = "white"

    button = tk.Button(
        frame,
        text=text,
        command=cmd,
        width=width,
        height=height,
        bg=__get_color(bg),
        fg=__get_color(fg),
        font=__get_font(font_size, bold),
        relief="flat",
    )
    if pack:
        button.pack(side=side, padx=padx, pady=pady)
    return button


def __add_cancel(frame: tk.Toplevel, side: str = "left") -> None:
    __add_button(frame, "Cancel", frame.destroy, side=side)


def __add_save(
    frame: tk.Toplevel, text: str, f1, f2, entity=None, d_dict: dict = None
) -> None:
    save_button = __add_button(
        frame=frame, text=text, cmd=lambda: f1(frame, f2, entity=entity, d_dict=d_dict)
    )
    frame.bind("<Return>", lambda event=None: save_button.invoke())


def __add_bonus_popup():
    popup_window = __create_popup(root, "Add Bonus", "Enter New Bonus Details")

    # Define configuration for each entry
    entry_configs = [
        {
            "label": "Bonus Percent",
            "textvariable": tk.StringVar(),
            "trace_function": __entry_float_check,
        },
        {
            "label": "Start Date",
            "textvariable": tk.StringVar(),
            "trace_function": __entry_date_check,
        },
    ]
    d_dict = __add_entries(popup_window, entry_configs)

    __add_save(
        popup_window,
        "Add",
        __attempt_save_user_input,
        __add_bonus,
        entity=None,
        d_dict=d_dict,
    )
    __add_cancel(popup_window)


def __update_value_popup():
    popup_window = __create_popup(root, "Recalulate Time Values", "Specify Time-ID")

    # Define configuration for each entry
    entry_configs = [
        {
            "label": "time_id",
            "textvariable": tk.StringVar(),
            "trace_function": __entry_int_check,
        }
    ]
    d_dict = __add_entries(popup_window, entry_configs)
    entry = d_dict["time_id"]["entry"]

    save_button = __add_button(
        popup_window,
        text="Update",
        cmd=lambda: __update_value_id(int(entry.get())),
        side="left",
    )
    popup_window.bind("<Return>", lambda event=None: save_button.invoke())

    __add_cancel(popup_window)


def __add_customer_popup():
    popup_window = __create_popup(root, "Add Customer", "Enter Customer Details")

    # Define configuration for each entry
    entry_configs = [
        {
            "label": "Customer Name",
            "textvariable": None,
            "trace_function": None,
        },
        {
            "label": "Start Date",
            "textvariable": tk.StringVar(),
            "trace_function": __entry_date_check,
        },
        {
            "label": "Wage",
            "textvariable": tk.StringVar(),
            "trace_function": __entry_int_check,
        },
    ]
    d_dict = __add_entries(popup_window, entry_configs)

    __add_save(
        popup_window,
        "Add",
        __attempt_save_user_input,
        __add_customer,
        entity=None,
        d_dict=d_dict,
    )
    __add_cancel(popup_window)


def __remove_customer_popup():
    popup_window = __create_popup(root, "Remove Customer", "Customer to Remove")

    projects = __get_active_projects()
    customers = projects["customer_name"].unique().tolist()
    combobox = __add_combobox(popup_window, customers)

    __add_save(
        popup_window,
        "Select",
        __attempt_remove_user_input,
        __disable_customer,
        entity=combobox,
        d_dict=None,
    )
    __add_cancel(popup_window)


def __add_project_popup():
    popup_window = __create_popup(root, "Enter New Project", "Enter Project Details")

    entry_configs = [
        {
            "label": "Project Name",
            "textvariable": None,
            "trace_function": None,
        },
        {
            "label": "Customer Name",
            "textvariable": None,
            "trace_function": None,
        },
    ]
    d_dict = __add_entries(popup_window, entry_configs)

    __add_save(
        popup_window,
        "Add",
        __attempt_save_user_input,
        __add_customer_project,
        entity=None,
        d_dict=d_dict,
    )
    __add_cancel(popup_window)


def __remove_project_popup():
    popup_window = __create_popup(root, "Remove Project", "Project to Remove")

    # Populate the Combobox with project names
    projects = __get_active_projects()
    text_names = []
    data_dict = {}
    for _, row in projects.iterrows():
        r_name = f"{row['customer_name']} - {row['project_name']}"
        data_dict[r_name] = {"p_id": row["project_id"]}
        text_names.append(r_name)
    combobox = __add_combobox(popup_window, text_names)

    __add_save(
        popup_window,
        "Select",
        __attempt_remove_user_input,
        __disable_customer_project,
        entity=combobox,
        d_dict=data_dict,
    )
    __add_cancel(popup_window)


def __summarize_data(tree: ttk.Treeview, label: tk.Label, time_index: int = 0) -> None:
    today = datetime.today()

    if time_index == 0:
        start_of_period = today - timedelta(days=today.weekday())
        end_of_period = start_of_period + timedelta(days=6)

        label.configure(text="Weekly Summary")
        start_date_key = start_of_period.strftime("%Y%m%d")
        end_date_key = end_of_period.strftime("%Y%m%d")
    elif time_index == 1:
        start_of_period = today.replace(day=1)
        if today.month == 12:
            end_of_period = today.replace(
                year=today.year + 1, month=1, day=1
            ) - timedelta(days=1)
        else:
            end_of_period = today.replace(month=today.month + 1, day=1) - timedelta(
                days=1
            )
        label.configure(text="Monthly Summary")
        start_date_key = start_of_period.strftime("%Y%m%d")
        end_date_key = end_of_period.strftime("%Y%m%d")
    else:
        start_date_key = time_index[0]
        end_date_key = time_index[1]
        label.configure(text="Custom Period Summary")

    grouped_data = pd.read_sql(
        f"select customer_name, project_name, round(sum(total_time),2) as total_time from time where date_key between '{start_date_key}' and '{end_date_key}' group by customer_name, project_name order by 1, 2",
        conn,
    )

    # Clear old data (if any)
    for row in tree.get_children():
        tree.delete(row)

    tree["columns"] = list(grouped_data.columns)  # Set column names
    tree["show"] = "headings"  # Hide default empty column

    # Add column headings
    for col in grouped_data.columns:
        tree.heading(col, text=col)  # Column title
        tree.column(col, width=200, anchor="center")  # Adjust column width

    # Insert DataFrame rows into Treeview
    for index, row in grouped_data.iterrows():
        tree.insert("", "end", values=list(row))

    # Pack Treeview in the window
    tree.pack(expand=True, fill="both")


def __add_summary_popup():
    popup_window = tk.Toplevel(root, bg=__get_color("beige"), width=600)
    popup_window.title("Time Summary")
    popup_window.resizable(False, False)

    label = __add_label(
        popup_window, "Weekly Summary", font_size=14, anchor="n", width=40
    )
    label.pack(padx=5, pady=5)

    tree = ttk.Treeview(popup_window)
    tree.pack(expand=True, fill="both")

    week_button = __add_button(
        frame=popup_window,
        text="Week",
        cmd=lambda: __summarize_data(tree=tree, time_index=0, label=label),
        side="left",
    )
    month_button = __add_button(
        frame=popup_window,
        text="Month",
        cmd=lambda: __summarize_data(tree=tree, time_index=1, label=label),
        side="left",
    )

    entry_s_date = tk.StringVar()
    entry_s_date.trace_add(
        "write", partial(__entry_date_check, entry_s_date, "yyyymmdd")
    )
    s_date = __add_entry(popup_window, entry_s_date, "Date", width=12, pack=False)
    s_date.insert(0, "20250101")
    s_date.pack(side="left", padx=5, pady=5)

    entry_e_date = tk.StringVar()
    entry_e_date.trace_add(
        "write", partial(__entry_date_check, entry_e_date, "yyyymmdd")
    )
    e_date = __add_entry(popup_window, entry_e_date, "Date", width=12, pack=False)
    e_date.insert(0, "20251231")
    e_date.pack(side="left", padx=5, pady=5)

    popup_window.bind(
        "<Return>",
        lambda event: __summarize_data(
            tree=tree, time_index=[s_date.get(), e_date.get()], label=label
        ),
    )

    __add_cancel(popup_window, side="right")

    # Default weekly
    __summarize_data(tree=tree, time_index=0, label=label)


def __add_sql_popup():
    popup_window = __create_popup(root, "SQL-Editor", "Enter SQL Command")
    popup_window.geometry("1200x600")

    menubar = tk.Menu(popup_window)
    popup_window.config(menu=menubar)

    file_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="Update", menu=file_menu)
    file_menu.add_command(label="Rerun Time Calculations", command=__update_value_popup)

    entry = __add_entry(popup_window, None, "SQL Command", width=200)

    sql_output_frame = tk.Frame(popup_window, bg=__get_color("beige"), width=1200)
    sql_output_frame.pack(fill=tk.BOTH, expand=True)
    sql_output = ttk.Treeview(sql_output_frame)
    sql_output.pack(fill=tk.BOTH, expand=True)

    h_scroll = ttk.Scrollbar(
        popup_window, orient="horizontal", command=sql_output.xview
    )
    h_scroll.pack(fill="x", side="bottom")
    sql_output.configure(xscrollcommand=h_scroll.set)

    sql_output.bind_all(
        "<MouseWheel>",
        lambda event: sql_output.yview_scroll(int(-1 * (event.delta / 6)), "units"),
    )
    sql_output.bind_all(
        "<Shift-MouseWheel>",
        lambda event: sql_output.xview_scroll(int(-1 * (event.delta / 6)), "units"),
    )

    entry.bind(
        "<Return>", lambda event: __run_sql(event, popup_window, entry, sql_output)
    )


def __add_project_button(c_name: str, p_name: str, state: bool, customer_index: int):
    col = "green" if state else "red"

    if customer_index == 0:
        button_frames.append(tk.Frame(frame, bg=__get_color("beige")))
        this_frame = button_frames[-1]
        this_frame.grid(column=0, row=len(button_frames))

        c_label = __add_label(this_frame, c_name)
        c_label.grid(column=0, row=0, padx=0, pady=2)

        separator = tk.Frame(this_frame, bg=__get_color("teal"), height=2, bd=0)
        separator.grid(column=0, row=1, columnspan=10, padx=5, sticky="ew", pady=5)

    else:
        this_frame = button_frames[-1]

    button = __add_button(
        this_frame,
        p_name,
        width=18,
        height=2,
        bg=col,
        pack=False,
        cmd=lambda c_name=c_name, p_name=p_name: __update_project(
            c_name, p_name, button
        ),
    )
    button.grid(column=customer_index, row=2, padx=5, pady=0)

    time = __get_value(c_name, p_name, user_input_date)
    formatted_value = __format_value(time)

    # Create text with total working time for the date
    total_time = __add_label(
        this_frame, formatted_value, height=2, font_size=11, bold=False
    )
    total_time.grid(column=customer_index, row=3, padx=5, pady=0)

    projects.append((c_name, p_name, total_time))


def __update_ui():
    global button_frames, projects, date_input
    for ui in button_frames:
        for widget in ui.winfo_children():
            widget.destroy()

    button_frames = []
    projects = []

    # Find all current projects
    sorted_projects = __get_active_projects()

    current_times = pd.read_sql(
        f"select * from time where date_key = '{today_date}' and end_time is null", conn
    )
    active_projects = current_times[
        current_times["project_id"].isin(sorted_projects["project_id"])
    ]

    customers = sorted_projects["customer_name"].unique().tolist()

    if len(customers) == 0:
        return
    customer_name = customers[0]
    customer_index = 0
    for i, row in enumerate(sorted_projects.iterrows()):
        c_name = row[1]["customer_name"]
        p_name = row[1]["project_name"]

        if c_name != customer_name:
            customer_index = 0
            customer_name = c_name
        elif i != 0:
            customer_index += 1

        state = False
        if (
            c_name in active_projects["customer_name"].tolist()
            and p_name in active_projects["project_name"].tolist()
        ):
            state = True

        __add_project_button(c_name, p_name, state, customer_index)

    def period_toggle_button():
        global time_index

        if time_index == 0:
            time_index = 1
            date_toggle.config({"text": "Current Week"})
        elif time_index == 1:
            time_index = 2
            date_toggle.config({"text": "Current Month"})
        elif time_index == 2:
            time_index = 3
            date_toggle.config({"text": "Current Year"})
        elif time_index == 3:
            time_index = 4
            date_toggle.config({"text": "All Time"})
        elif time_index == 4:
            time_index = 0
            date_toggle.config({"text": "Current Date"})

        __update_value()

    def format_toggle_button():
        global data_format

        if data_format == 0:
            data_format = 1
            format_toggle.config({"text": "0.0 h"})
        elif data_format == 1:
            data_format = 2
            format_toggle.config({"text": "SEK"})
        elif data_format == 2:
            data_format = 0
            format_toggle.config({"text": "0 h 0 min"})

        __update_value()

    ## Date Selection
    entry_date = tk.StringVar()
    entry_date.trace_add("write", partial(__entry_date_check, entry_date, "yyyymmdd"))

    date_input = tk.Entry(
        frame_date_input, width=14, font=__get_font(14), textvariable=entry_date
    )
    date_input.config({"background": __get_color("background")})
    date_input.insert(0, user_input_date)
    date_input.bind("<Return>", __update_user_input_date)
    date_input.grid(column=0, row=1, padx=5, pady=5)

    date_toggle = __add_button(
        frame_date_input,
        "Current Date",
        period_toggle_button,
        pack=False,
        width=13,
        font_size=12,
    )
    date_toggle.grid(column=0, row=2, padx=5, pady=5)

    format_toggle = __add_button(
        frame_date_input,
        "0 h 0 min",
        format_toggle_button,
        pack=False,
        width=13,
        font_size=12,
    )
    format_toggle.grid(column=1, row=2, padx=5, pady=5)


### Main Code ###
def start_program():
    menubar = tk.Menu(root)
    root.config(menu=menubar)

    file_menu = tk.Menu(menubar, tearoff=0)
    sql_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="File", menu=file_menu)
    file_menu.add_command(label="Add Customer", command=__add_customer_popup)
    file_menu.add_command(label="Remove Customer", command=__remove_customer_popup)
    file_menu.add_separator()
    file_menu.add_command(label="Add Project", command=__add_project_popup)
    file_menu.add_command(label="Remove Project", command=__remove_project_popup)
    file_menu.add_separator()
    file_menu.add_command(label="Add Bonus", command=__add_bonus_popup)
    file_menu.add_separator()
    file_menu.add_command(label="Exit", command=root.quit)
    menubar.add_cascade(label="SQL", menu=sql_menu)
    sql_menu.add_command(label="Run SQL", command=__add_sql_popup)
    sql_menu.add_command(label="Summarize", command=__add_summary_popup)

    __update_ui()


def initialize_ui() -> tk.Tk:
    root = tk.Tk()
    root.title("Work Timer v2")
    root.wm_iconbitmap("program_logo.ico")

    frame = tk.Frame(root, bg=__get_color("beige"))
    frame.pack(fill=tk.BOTH, expand=True)

    return root, frame


### INIT ###

# Initialize the database
conn = initialize_db(db_file)

COLS = {
    "beige": "#FCE09B",
    "red": "#B2533E",
    "green": "#B5CB99",
    "teal": "#186F65",
    "white": "#FFFFFF",
    "background": "#FDEFD4",
}

time_index = 0
data_format = 0

root, frame = initialize_ui()

button_frames = []
projects = []

frame_date_input = tk.Frame(root, bg=__get_color("beige"))
frame_date_input.pack(fill=tk.BOTH, expand=True)

today_date = __format_date_key(datetime.now())
user_input_date = int(today_date)

start_program()
root.mainloop()


# Close the conn
conn.close()
