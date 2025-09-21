import sqlite3
import pandas as pd
from datetime import datetime, timedelta


class Database:
    db = None

    def __init__(self, db_file: str):
        self.pre_run_log = []
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        Database.db = self

    def initialize_db(self):
        """
        Initialize the database by creating necessary tables, triggers, and populating the dates table.
        """

        def add_default_settings():
            # Build the date table https://dearpygui.readthedocs.io/en/latest/documentation/themes.html
            color_settings = [
                ("mvThemeCol_Text", (255, 255, 255, 255), "Main text color"),
                (
                    "mvThemeCol_TextDisabled",
                    (100, 0, 0, 255),
                    "Disabled text color (ex. dates not in current month)",
                ),
                (
                    "mvThemeCol_WindowBg",
                    (37, 37, 37, 255),
                    "Background outside main containers",
                ),
                (
                    "mvThemeCol_ChildBg",
                    (37, 37, 37, 255),
                    "Background inside child containers",
                ),
                ("mvThemeCol_PopupBg", (37, 37, 37, 255), "Background for popups"),
                (
                    "mvThemeCol_Border",
                    (20, 20, 20, 255),
                    "Border color for containers and popups",
                ),
                (
                    "mvThemeCol_BorderShadow",
                    (128, 0, 128, 255),
                    "Shadow color for borders",
                ),
                (
                    "mvThemeCol_TitleBgActive",
                    (15, 86, 135, 255),
                    "Title bar background (active)",
                ),
                (
                    "mvThemeCol_TitleBgCollapsed",
                    (255, 0, 0, 255),
                    "Title bar background (collapsed)",
                ),
                (
                    "mvThemeCol_FrameBg",
                    (50, 50, 50, 255),
                    "Input field background",
                ),
                (
                    "mvThemeCol_FrameBgHovered",
                    (128, 128, 128, 255),
                    "Input field background (hovered)",
                ),
                (
                    "mvThemeCol_FrameBgActive",
                    (220, 220, 220, 255),
                    "Input field background (active/clicked)",
                ),
                ("mvThemeCol_TitleBg", (37, 37, 37, 255), "Title bar background"),
                ("mvThemeCol_Button", (50, 50, 50, 255), "Button background color"),
                (
                    "mvThemeCol_ButtonHovered",
                    (128, 128, 128, 255),  # 34, 83, 117
                    "Button color (hovered)",
                ),
                (
                    "mvThemeCol_ButtonActive",
                    (220, 220, 220, 255),  # 24, 63, 87
                    "Button color (active/clicked)",
                ),
                (
                    "mvThemeCol_CheckMark",
                    (0, 120, 215, 255),
                    "Checkmark color for selected radio buttons and checkboxes",
                ),
            ]

            rows = [
                {
                    "setting_name": name,
                    "setting_type": "ui_color",
                    "setting_description": desc,
                    "red": r,
                    "green": g,
                    "blue": b,
                    "alpha": a,
                }
                for name, (r, g, b, a), desc in color_settings
            ]

            # Create DataFrame
            settings_table = pd.DataFrame(rows)
            settings_table.to_sql(
                "settings", self.conn, if_exists="append", index=False
            )

        def add_dates(s_date, e_date):
            """
            Add a range of dates to the 'dates' table.
            """
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

            # Insert the date table into the database
            date_table.to_sql("dates", self.conn, if_exists="append", index=False)

        try:
            # Log the initialization process
            self.pre_run_log.append("Initializing database...")

            ## Time Table
            df_temp = self.fetch_query(
                "select * from sqlite_master where type = 'table' and name = 'time'"
            )
            if df_temp.empty:
                self.execute_query("""
                create table if not exists time (
                    time_id integer primary key autoincrement,
                    customer_id integer,
                    customer_name text,
                    project_id integer,
                    project_name text,
                    date_key integer,
                    start_time datetime,
                    end_time datetime,
                    total_time real,
                    wage real,
                    bonus real,
                    cost real,
                    user_bonus real,
                    git_id integer default 0,
                    comment text
                )
                """)
                self.pre_run_log.append("Table 'time' created successfully.")

                ## Trigger for Time Table
                self.execute_query("""
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
                self.pre_run_log.append(
                    "Trigger 'trigger_time_after_update' created successfully."
                )

                # Single trigger for project_name after INSERT or UPDATE of project_id
                self.execute_query("""
                create trigger if not exists trigger_time_insert_row
                after insert on time
                for each row
                begin
                    update time
                    set 
                         project_name = (
                            select project_name from projects where project_id = new.project_id
                         )
                        ,customer_name = (
                            select customer_name from customers where customer_id = new.customer_id
                        )
                        ,wage = (
                            select wage from customers where customer_id = new.customer_id
                        )
                        ,bonus = (
                            select bonus_percent from bonus
                                where current_date between start_date and ifnull(end_date, '2099-12-31')
                        )
                    where time_id = new.time_id;
                end;
                """)
                self.execute_query("""
                create trigger if not exists trigger_time_update_row
                after update of project_id on time
                for each row
                begin
                    update time
                    set 
                         project_name = (
                            select project_name from projects where project_id = new.project_id
                         )
                        ,customer_name = (
                            select customer_name from customers where customer_id = new.customer_id
                         )
                    where time_id = new.time_id;
                end;
                """)
                self.pre_run_log.append(
                    "Triggers for customer_name, project_name, wage and bonus created successfully."
                )

            ## Customers Table
            df_temp = self.fetch_query(
                "select * from sqlite_master where type = 'table' and name = 'customers'"
            )
            if df_temp.empty:
                self.execute_query("""
                create table if not exists customers (
                    customer_id integer primary key autoincrement,
                    customer_name text,
                    start_date datetime,
                    wage real,
                    sort_order integer default 1,
                    pat_token text,
                    org_url text,
                    valid_from datetime,
                    valid_to datetime,
                    is_current integer,
                    inserted_at datetime
                )
                """)
                self.pre_run_log.append("Table 'customers' created successfully.")

            ## Projects Table
            df_time = self.fetch_query(
                "select * from sqlite_master where type = 'table' and name = 'projects'"
            )
            if df_time.empty:
                self.execute_query("""
                create table if not exists projects (
                    project_id integer primary key autoincrement,
                    customer_id integer,
                    project_name text,
                    git_id integer default 0,
                    is_current boolean
                )
                """)
                self.pre_run_log.append("Table 'projects' created successfully.")

            ## Bonus Table
            df_time = self.fetch_query(
                "select * from sqlite_master where type = 'table' and name = 'bonus'"
            )
            if df_time.empty:
                self.execute_query("""
                create table if not exists bonus (
                    bonus_id integer primary key autoincrement,
                    bonus_percent real,
                    start_date text,
                    end_date text
                )
                """)
                self.pre_run_log.append("Table 'bonus' created successfully.")

            ## Dates Table
            df_time = self.fetch_query(
                "select * from sqlite_master where type = 'table' and name = 'dates'"
            )
            if df_time.empty:
                self.execute_query("""
                create table if not exists dates (
                    date_key integer unique,
                    date text unique,
                    year integer,
                    month integer,
                    week integer,
                    day integer
                )
                """)
                self.pre_run_log.append("Table 'dates' created successfully.")

                # Populate the dates table
                try:
                    add_dates(s_date="2020-01-01", e_date="2030-12-31")
                    self.pre_run_log.append("Dates table populated successfully.")
                except Exception as e:
                    self.pre_run_log.append(f"Error populating dates table: {e}")

            ## UI Settings table
            df_time = self.fetch_query(
                "select * from sqlite_master where type = 'table' and name = 'settings'"
            )
            if df_time.empty:
                self.execute_query("""
                create table if not exists settings (
                    setting_name text unique,
                    setting_type text,
                    setting_description text,
                    red integer not null,
                    green integer not null,
                    blue integer not null,
                    alpha integer not null
                )
                """)
                self.pre_run_log.append("Table 'settings' created successfully.")

                try:
                    add_default_settings()
                    self.pre_run_log.append("Settings table populated successfully.")
                except Exception as e:
                    self.pre_run_log.append(f"Error populating settings table: {e}")

        except Exception as e:
            self.pre_run_log.append(f"Error initializing database: {e}")
        finally:
            self.conn.commit()
            self.pre_run_log.append("Database loaded withouter errors!")

        ### Time Table Operations ###

    def insert_time_row(
        self, customer_id: int, project_id: int, git_id: int = None, comment: str = None
    ):
        dt = datetime.now()
        now = dt.strftime("%Y-%m-%d %H:%M:%S")
        date_key = int(dt.strftime("%Y%m%d"))

        # Check if there's an active timer
        rows = self.fetch_query(
            """
            select time_id, start_time, end_time
            from time
            where customer_id = ? and project_id = ? and end_time is null
            order by time_id desc
        """,
            (customer_id, project_id),
        )

        if rows.empty:
            # Insert a new row with the current time as start_time
            self.execute_query(
                """
                insert into time (customer_id, project_id, start_time, date_key)
                values (?, ?, ?, ?)
            """,
                (
                    customer_id,
                    project_id,
                    now,
                    date_key,
                ),
            )
            print(
                f"Starting timer for customer_id: {customer_id}, project_id: {project_id}"
            )  # TODO add logging
        else:
            # Update the latest row with blank end_time
            last_row_id = int(rows.iloc[0]["time_id"])

            self.execute_query(
                """
                update time
                set
                    end_time = ?,
                    comment = ?,
                    git_id = ?
                where time_id = ?
            """,
                (now, comment, git_id, last_row_id),
            )
            print(
                f"Ending timer for customer_id: {customer_id}, project_id: {project_id}"
            )  ## TODO logging

    def delete_time_row(self, customer_id: int, project_id: int) -> None:
        """
        Delete the latest time entry for a given customer and project.
        """
        self.execute_query(
            """
            delete
            from time
            where customer_id = ? and project_id = ? and end_time is null
        """,
            (customer_id, project_id),
        )

    def get_customer_ui_list(self, start_date: str, end_date: str):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        query = f"""
            with calculated_time as (
                select
                    p.customer_id,
                    c.customer_name,
                    p.project_id,
                    p.project_name,
                    ifnull(sum(
                        ifnull(t.total_time, (julianday('{now}') - julianday(start_time)) * 24)
                    ), 0) as total_time,
                    ifnull(sum(
                        ifnull(t.total_time, (julianday('{now}') - julianday(start_time)) * 24)
                        * ifnull(t.wage, 0)
                        * ifnull(t.bonus, 0)
                    ), 0) as user_bonus
                    ,min(coalesce(c.sort_order, 0)) as sort_order
                from projects p
                join customers c on c.customer_id = p.customer_id and c.is_current = 1
                left join time t on t.customer_id = p.customer_id and t.project_id = p.project_id
                    and t.date_key between {start_date} and {end_date}
                where p.is_current = 1
                group by
                    p.customer_id,
                    c.customer_name,
                    p.project_id,
                    p.project_name
            )
            select
                ct.customer_id,
                ct.customer_name,
                ct.project_id,
                ct.project_name,
                round(ct.total_time, 2) as total_time,
                round(ct.user_bonus, 2) as user_bonus,
                sort_order
            from calculated_time ct
            order by sort_order asc;
        """
        result = self.fetch_query(query)
        return result

    def get_data_input_list(self):
        query = """
            select 
                c.customer_name, 
                c.customer_id, 
                p.project_name, 
                p.project_id,
                p.git_id, 
                c.wage, 
                c.org_url, 
                c.pat_token,
                p.is_current as p_current, 
                c.is_current as c_current 
            from projects p
            left join customers c on c.customer_id = p.customer_id
        """
        result = self.fetch_query(query)
        return result

    # def queue_task(self, action: str, data: dict, response=None):
    #     """
    #     Add a task to the queue.
    #     """
    #     self.queue.put(
    #         {
    #             "action": action,
    #             "data": data,
    #             "response": response,  # Optional
    #         }
    #     )

    # def process_queue(self):
    #     """
    #     Process tasks in the queue.
    #     """
    #     while not self.queue.empty():
    #         task = self.queue.get()
    #         action = task["action"]
    #         data = task["data"]
    #         response = task["response"]

    #         try:
    #             if action == "insert_customer":
    #                 self.insert_customer(
    #                     customer_name=data["customer_name"],
    #                     start_date=data["start_date"],
    #                     wage=int(data["wage"]),
    #                     pat_token=data.get("pat_token"),
    #                     org_url=data.get("org_url"),
    #                 )
    #             elif action == "update_customer":
    #                 self.update_customer(
    #                     customer_name=data["customer_name"],
    #                     new_customer_name=data["new_customer_name"],
    #                     wage=int(data["wage"]),
    #                     org_url=data.get("org_url"),
    #                     pat_token=data.get("pat_token"),
    #                 )
    #             elif action == "remove_customer":
    #                 self.remove_customer(data["customer_name"])
    #             elif action == "enable_customer":
    #                 self.enable_customer(data["customer_name"])
    #             elif action == "insert_project":
    #                 self.insert_project(
    #                     data["customer_name"], data["project_name"], data["git_id"]
    #                 )
    #             elif action == "update_project":
    #                 self.update_project(
    #                     data["customer_name"],
    #                     data["project_name"],
    #                     data["new_project_name"],
    #                     data["new_git_id"],
    #                 )
    #             elif action == "delete_project":
    #                 self.remove_project(data["customer_name"], data["project_name"])
    #             elif action == "enable_project":
    #                 self.enable_project(data["customer_name"], data["project_name"])
    #             elif action == "insert_bonus":
    #                 self.insert_bonus(data["start_date"], data["amount"])
    #             elif action == "get_customer_update":
    #                 result = self.fetch_query(
    #                     "select wage, org_url, pat_token from customers where customer_name = ? and is_current = 1",
    #                     (data["customer_name"],),
    #                 )
    #                 if response:
    #                     response.put(result)
    #             elif action == "get_bonus":
    #                 result = self._get_value_from_db(
    #                     "select bonus_percent from bonus where ? between start_date and ifnull(end_date, '2099-12-31')",
    #                     (data["date"],),
    #                     data_type="float",
    #                 )
    #                 if response:
    #                     response.put(result)
    #             elif action == "get_customer_name_from_cid":
    #                 result = self._get_value_from_db(
    #                     "select customer_name from customers where customer_id = ?",
    #                     (data["customer_id"],),
    #                 )
    #                 if response:
    #                     response.put(result)
    #             elif action == "get_project_name_from_pid":
    #                 result = self._get_value_from_db(
    #                     "select project_name from projects where project_id = ?",
    #                     (data["project_id"],),
    #                 )
    #                 if response:
    #                     response.put(result)
    #             elif action == "get_active_customers":
    #                 result = self.fetch_query("""
    #                     select distinct c.customer_name
    #                     from projects p
    #                     left join customers c on c.customer_id = p.customer_id and p.is_current = 1
    #                     where c.is_current = 1
    #                 """)
    #                 if response:
    #                     response.put(result["customer_name"].unique().tolist())
    #             elif action == "get_inactive_customers":
    #                 result = self.fetch_query("""
    #                     select c.customer_name
    #                     from customers c
    #                     group by c.customer_name
    #                     having sum(c.is_current) = 0
    #                 """)
    #                 if response:
    #                     response.put(result["customer_name"].unique().tolist())
    #             elif action == "get_customers_with_inactive_projects":
    #                 result = self.fetch_query("""
    #                     select c.customer_name
    #                     from projects p
    #                     left join customers c on c.customer_id = p.customer_id
    #                     where p.is_current = 0
    #                 """)
    #                 if response:
    #                     response.put(result["customer_name"].unique().tolist())
    #             elif action == "get_customer_names":
    #                 result = self.fetch_query(
    #                     "select customer_name from customers where is_current = 1"
    #                 )
    #                 if response:
    #                     response.put(result["customer_name"].unique().tolist())
    #             elif action == "get_customer_ui_list":
    #                 now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    #                 query = f"""
    #                     with calculated_time as (
    #                         select
    #                             p.customer_id,
    #                             c.customer_name,
    #                             p.project_id,
    #                             p.project_name,
    #                             ifnull(sum(
    #                                 ifnull(t.total_time, (julianday('{now}') - julianday(start_time)) * 24)
    #                             ), 0) as total_time,
    #                             ifnull(sum(
    #                                 ifnull(t.total_time, (julianday('{now}') - julianday(start_time)) * 24)
    #                                 * ifnull(t.wage, 0)
    #                                 * ifnull(t.bonus, 0)
    #                             ), 0) as user_bonus
    #                             ,min(coalesce(c.sort_order, 0)) as sort_order
    #                         from projects p
    #                         join customers c on c.customer_id = p.customer_id and c.is_current = 1
    #                         left join time t on t.customer_id = p.customer_id and t.project_id = p.project_id
    #                             and t.date_key between {data["start_date"]} and {data["end_date"]}
    #                         where p.is_current = 1
    #                         group by
    #                             p.customer_id,
    #                             c.customer_name,
    #                             p.project_id,
    #                             p.project_name
    #                     )
    #                     select
    #                         ct.customer_id,
    #                         ct.customer_name,
    #                         ct.project_id,
    #                         ct.project_name,
    #                         round(ct.total_time, 2) as total_time,
    #                         round(ct.user_bonus, 2) as user_bonus,
    #                         sort_order
    #                     from calculated_time ct
    #                     order by sort_order asc;
    #                 """
    #                 result = self.fetch_query(query)
    #                 if response:
    #                     response.put(result)
    #             elif action == "get_project_names":
    #                 result = self.fetch_query(
    #                     """
    #                     select p.project_name
    #                     from projects p
    #                     left join customers c on c.customer_id = p.customer_id
    #                     where c.customer_name = ? and p.is_current = 1
    #                 """,
    #                     (data["customer_name"],),
    #                 )
    #                 if response:
    #                     response.put(result["project_name"].unique().tolist())
    #             elif action == "get_inactive_project_names":
    #                 result = self.fetch_query(
    #                     """
    #                     select p.project_name
    #                     from projects p
    #                     left join customers c on c.customer_id = p.customer_id
    #                     where c.customer_name = ? and p.is_current = 0
    #                 """,
    #                     (data["customer_name"],),
    #                 )
    #                 if response:
    #                     response.put(result["project_name"].unique().tolist())
    #             elif action == "get_df":
    #                 result = self.fetch_query(data["query"])
    #                 if response:
    #                     response.put(result)
    #             elif action == "run_query":
    #                 query = data["query"].strip()
    #                 if query.lower().startswith("select") or query.lower().startswith(
    #                     "with"
    #                 ):
    #                     result = self.fetch_query(query)
    #                 else:
    #                     self.execute_query(query)
    #                     result = []
    #                 if response:
    #                     response.put(result)
    #             elif action == "run_cursor":
    #                 query = data["query"]
    #                 params = data.get("params", ())
    #                 cursor = self.conn.execute(query, params)
    #                 result = cursor.fetchall()
    #                 if response:
    #                     response.put(result)
    #         except Exception as e:
    #             if response:
    #                 response.put(e)

    # ### Customer Table Operations ###
    # def insert_customer(
    #     self,
    #     customer_name: str,
    #     start_date: str,
    #     wage: int,
    #     org_url: str = None,
    #     pat_token: str = None,
    #     valid_from: str = None,
    # ):
    #     now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    #     if not valid_from:
    #         valid_from = datetime.now().strftime("%Y-%m-%d")
    #         if valid_from > start_date:
    #             valid_from = start_date

    #     date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    #     day_before = date_obj - timedelta(days=1)
    #     valid_to = day_before.strftime("%Y-%m-%d")

    #     query = """
    #         select
    #             case
    #                 when exists (select 1 from customers where customer_name = ?)
    #                 then (select sort_order from customers where customer_name = ?)
    #                 else (select ifnull(max(sort_order), 0) + 1 from customers)
    #             end as sort_order
    #     """
    #     result = self.fetch_query(query, (customer_name, customer_name))
    #     sort_order = int(result.iloc[0, 0])

    #     self.execute_query(
    #         """
    #         update customers
    #         set
    #             is_current = 0,
    #             valid_to = ?
    #         where customer_name = ? and is_current = 1
    #     """,
    #         (valid_to, customer_name),
    #     )

    #     self.execute_query(
    #         """
    #         insert into customers (customer_name, start_date, wage, sort_order, pat_token, org_url, valid_from, valid_to, is_current, inserted_at)
    #         values (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    #     """,
    #         (
    #             customer_name,
    #             start_date,
    #             wage,
    #             sort_order,
    #             pat_token,
    #             org_url,
    #             valid_from,
    #             None,
    #             now,
    #         ),
    #     )

    # def update_customer(
    #     self,
    #     customer_name: str,
    #     new_customer_name: str,
    #     wage: int,
    #     org_url: str = None,
    #     pat_token: str = None,
    # ):
    #     self.execute_query(
    #         """
    #         update customers
    #         set
    #             customer_name = ?,
    #             wage = ?,
    #             org_url = ?,
    #             pat_token = ?
    #         where customer_name = ?
    #     """,
    #         (new_customer_name, wage, org_url, pat_token, customer_name),
    #     )

    #     self.execute_query(
    #         """
    #         update time
    #         set
    #             customer_name = ?,
    #             wage = ?
    #         where customer_name = ?
    #     """,
    #         (new_customer_name, wage, customer_name),
    #     )

    # def remove_customer(self, customer_name: str):
    #     self.execute_query(
    #         """
    #         update customers
    #         set is_current = 0
    #         where customer_name = ?
    #     """,
    #         (customer_name,),
    #     )

    # def enable_customer(self, customer_name: str):
    #     self.execute_query(
    #         """
    #         update customers
    #         set is_current = 1
    #         where customer_name = ?
    #     """,
    #         (customer_name,),
    #     )

    # ### Project Table Operations ###
    # def insert_project(self, customer_name: str, project_name: str, git_id: int = None):
    #     customer_id = self._get_value_from_db(
    #         "select customer_id from customers where customer_name = ? and is_current = 1",
    #         (customer_name,),
    #         data_type="int",
    #     )

    #     existing_projects = self.fetch_query(
    #         """
    #         select * from projects
    #         where project_name = ? and customer_id = ?
    #     """,
    #         (project_name, customer_id),
    #     )

    #     if not existing_projects.empty and existing_projects["is_current"].iloc[0] == 1:
    #         return  # Project already exists in database!
    #     elif not existing_projects.empty:
    #         project_id = existing_projects["project_id"].iloc[0]
    #         self.execute_query(
    #             "update projects set is_current = 1 where project_id = ?", (project_id,)
    #         )
    #     else:
    #         self.execute_query(
    #             """
    #             insert into projects (customer_id, project_name, is_current, git_id)
    #             values (?, ?, 1, ?)
    #         """,
    #             (customer_id, project_name, git_id),
    #         )

    # def update_project(
    #     self,
    #     customer_name: str,
    #     project_name: str,
    #     new_project_name: str,
    #     new_git_id: int = None,
    # ):
    #     self.execute_query(
    #         """
    #         update projects
    #         set
    #             project_name = ?,
    #             git_id = ?
    #         where project_name = ? and customer_id = (
    #             select customer_id from customers where customer_name = ? and is_current = 1
    #         )
    #     """,
    #         (new_project_name, new_git_id, project_name, customer_name),
    #     )

    #     self.execute_query(
    #         """
    #         update time
    #         set
    #             project_name = ?
    #         where project_name = ? and customer_name = ?
    #     """,
    #         (new_project_name, project_name, customer_name),
    #     )

    # def remove_project(self, customer_name: str, project_name: str):
    #     self.execute_query(
    #         """
    #         update projects
    #         set is_current = 0
    #         where project_name = ? and is_current = 1 and customer_id in (
    #             select customer_id from customers where customer_name = ? and is_current = 1
    #         )
    #     """,
    #         (project_name, customer_name),
    #     )

    # def enable_project(self, customer_name: str, project_name: str):
    #     self.execute_query(
    #         """
    #         update projects
    #         set is_current = 1
    #         where project_name = ? and customer_id in (
    #             select customer_id from customers where customer_name = ?
    #         )
    #     """,
    #         (project_name, customer_name),
    #     )

    # ## Modify Bonus Table
    # def insert_bonus(self, start_date: str, amount: float) -> None:
    #     day_before_start_date = (
    #         datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)
    #     ).strftime("%Y-%m-%d")
    #     self.execute_query(
    #         f"update bonus set end_date = '{day_before_start_date}' where end_date is Null"
    #     )

    #     self.execute_query(
    #         "insert into bonus (start_date, bonus_percent) values (?, ?)",
    #         (start_date, round(amount, 3)),
    #     )

    def execute_query(self, query: str, params: tuple = ()):
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
        except Exception as e:
            print(f"Error executing query: {query}\n{e}")
            raise

    def fetch_query(self, query: str, params: tuple = ()):
        try:
            return pd.read_sql(query, self.conn, params=params)
        except Exception as e:
            print(
                f"Error fetching query: {query}\n{e}"
            )  # TODO maybe pass logger function with for usage?
            raise

    def smart_query(self, query: str, params: tuple = ()):
        """
        Execute any SQL query. If the query returns rows, return a DataFrame.
        If not, commit and return None.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            if cursor.description:  # Query returns rows
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                return pd.DataFrame(rows, columns=columns)
            else:  # Query does not return rows
                self.conn.commit()
                return None
        except Exception as e:
            print(f"Error executing/fetching query: {query}\n{e}")
            raise

    def _get_value_from_db(
        self, query: str, params: tuple = (), data_type: str = "str"
    ):
        result = self.fetch_query(query, params)
        if not result.empty:
            val = result.iloc[0, 0]
        else:
            val = None

        if data_type == "str":
            return val if val is not None else ""
        elif data_type == "int":
            return int(val) if val is not None else 0
        elif data_type == "float":
            return float(val) if val is not None else 0.0
        else:
            raise ValueError("Invalid data type specified.")

    def close(self):
        self.conn.close()
