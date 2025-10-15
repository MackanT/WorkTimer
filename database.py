import sqlite3
from textwrap import dedent
import pandas as pd
from datetime import datetime, timedelta


class Database:
    db = None

    def __init__(self, db_file: str, log_engine):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        Database.db = self
        self.log_engine = log_engine

    def initialize_db(self):
        """
        Initialize the database by creating necessary tables, triggers, and populating the dates table.
        """

        def add_default_queries():
            query_settings = [
                (
                    "time",
                    """
                select
                     time_id
                    ,start_time, end_time, round(total_time, 2) as total_time
                    ,customer_id, customer_name
                    ,project_id, project_name
                    ,git_id, comment
                from time
                order by time_id desc
                limit 100
                """,
                ),
                (
                    "customers",
                    """
                select
                     customer_id
                    ,customer_name
                    ,wage
                    ,org_url
                    ,pat_token
                from customers
                where is_current = 1
                """,
                ),
                (
                    "projects",
                    """
                select
                     project_id
                    ,project_name
                    ,customer_id
                    ,git_id
                from projects
                where is_current = 1
                """,
                ),
                (
                    "weekly",
                    """
                select
                     t.customer_name
                    ,t.project_name
                    ,round(sum(t.total_time), 2) as total_time
                from time t
                left join dates d on d.date_key = t.date_key
                where d.year = cast(strftime('%Y', 'now') as integer)
                    and d.week = (select week from dates where date = date('now') limit 1)
                group by t.customer_name, t.project_name
                having sum(t.total_time) > 0
                union all
                select '', '', ''
                union all
                select
                     t.customer_name
                    ,'total' as project_name
                    ,round(sum(t.total_time), 2) as total_time
                from time t
                left join dates d on d.date_key = t.date_key
                where d.year = cast(strftime('%Y', 'now') as integer)
                    and d.week = (select week from dates where date = date('now') limit 1)
                group by t.customer_name
                having sum(t.total_time) > 0
                """,
                ),
                (
                    "monthly",
                    """
                select
                     t.customer_name
                    ,t.project_name
                    ,round(sum(t.total_time), 2) as total_time
                from time t
                left join dates d on d.date_key = t.date_key
                where d.year = cast(strftime('%Y', 'now') as integer)
                    and d.month = cast(strftime('%m', 'now') as integer)
                group by t.customer_name, t.project_name
                having sum(t.total_time) > 0
                union all
                select '', '', ''
                union all
                select
                     t.customer_name
                    ,'total' as project_name
                    ,round(sum(t.total_time), 2) as total_time
                from time t
                left join dates d on d.date_key = t.date_key
                where d.year = cast(strftime('%Y', 'now') as integer)
                   and d.month = cast(strftime('%m', 'now') as integer)
                group by t.customer_name
                having sum(t.total_time) > 0
                """,
                ),
            ]

            def remove_leading_blank_line(sql_code: str) -> str:
                lines = sql_code.splitlines()
                if lines and lines[0].strip() == "":
                    lines = lines[1:]
                return "\n".join(lines)

            rows = [
                {
                    "query_name": name,
                    "query_sql": remove_leading_blank_line(dedent(sql_code)),
                    "is_default": 1,
                }
                for name, sql_code in query_settings
            ]

            # Create DataFrame
            queries_table = pd.DataFrame(rows)
            queries_table.to_sql("queries", self.conn, if_exists="append", index=False)

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
            self.log_engine.log("INFO", "Initializing database...")

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
                self.log_engine.log("INFO", "Table 'time' created successfully.")

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
                self.log_engine.log(
                    "INFO", "Trigger 'trigger_time_after_update' created successfully."
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
                self.log_engine.log(
                    "INFO",
                    "Triggers for customer_name, project_name, wage and bonus created successfully.",
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
                self.log_engine.log("INFO", "Table 'customers' created successfully.")

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
                self.log_engine.log("INFO", "Table 'projects' created successfully.")

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
                self.log_engine.log("INFO", "Table 'bonus' created successfully.")

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
                self.log_engine.log("INFO", "Table 'dates' created successfully.")

                # Populate the dates table
                try:
                    add_dates(s_date="2020-01-01", e_date="2030-12-31")
                    self.log_engine.log("INFO", "Dates table populated successfully.")
                except Exception as e:
                    self.log_engine.log("ERROR", f"Error populating dates table: {e}")

            ## Query Snippets table
            df_time = self.fetch_query(
                "select * from sqlite_master where type = 'table' and name = 'queries'"
            )
            if df_time.empty:
                self.execute_query("""
                create table if not exists queries (
                    query_name text unique,
                    query_sql text not null,
                    is_default boolean
                )
                """)
                self.log_engine.log("INFO", "Table 'queries' created successfully.")

                try:
                    add_default_queries()
                    self.log_engine.log("INFO", "Queries table populated successfully.")
                except Exception as e:
                    self.log_engine.log("ERROR", f"Error populating queries table: {e}")

        except Exception as e:
            self.log_engine.log("ERROR", f"Error initializing database: {e}")
        finally:
            self.conn.commit()
            self.log_engine.log("INFO", "Database loaded without errors!")

    ### Time Table Operations ###

    def insert_time_row(
        self, customer_id: int, project_id: int, git_id: int = None, comment: str = None
    ):
        dt = datetime.now()
        now = dt.strftime("%Y-%m-%d %H:%M:%S")
        date_key = int(dt.strftime("%Y%m%d"))

        customer_name = self.get_customer_name(customer_id)
        project_name = self.get_project_name(project_id)

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
            self.log_engine.log_msg(
                "INFO",
                f"Starting timer for customer: {customer_name} - project: {project_name}",
            )
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
            self.log_engine.log_msg(
                "INFO",
                f"Ending timer for customer: {customer_name} - project: {project_name}",
            )

    def delete_time_row(self, customer_id: int, project_id: int) -> None:
        """
        Delete the latest time entry for a given customer and project.
        """
        customer_name = self.get_customer_name(customer_id)
        project_name = self.get_project_name(project_id)

        self.execute_query(
            """
            delete
            from time
            where customer_id = ? and project_id = ? and end_time is null
        """,
            (customer_id, project_id),
        )
        self.log_engine.log_msg(
            "INFO",
            f"Deleted latest time entry for customer: {customer_name} - project: {project_name}",
        )

    ### Customer Table Operations ###

    def insert_customer(
        self,
        customer_name: str,
        start_date: str,
        wage: int,
        org_url: str = None,
        pat_token: str = None,
        valid_from: str = None,
    ):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not valid_from:
            valid_from = min(start_date, datetime.now().strftime("%Y-%m-%d"))

        date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        day_before = date_obj - timedelta(days=1)
        valid_to = day_before.strftime("%Y-%m-%d")

        # Find the old customer_id (to be set to is_current=0)
        old_customer_id = self._get_value_from_db(
            "select customer_id from customers where customer_name = ? and is_current = 1",
            (customer_name,),
            data_type="int",
        )

        if old_customer_id:
            self.execute_query(
                """
                update customers
                set
                    is_current = 0,
                    valid_to = ?
                where customer_name = ? and is_current = 1
            """,
                (valid_to, customer_name),
            )
            self.log_engine.log_msg(
                "INFO",
                f"Disabled '{customer_name}' old id: {old_customer_id}",
            )

        # Insert new customer row
        self.execute_query(
            """
            insert into customers (customer_name, start_date, wage, pat_token, org_url, valid_from, valid_to, is_current, inserted_at)
            values (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
            (
                customer_name,
                start_date,
                wage,
                pat_token,
                org_url,
                valid_from,
                None,
                now,
            ),
        )
        self.log_engine.log_msg("INFO", f"Inserted new customer '{customer_name}'")

        # Get the new customer_id
        new_customer_id = self._get_value_from_db(
            "select customer_id from customers where customer_name = ? and is_current = 1",
            (customer_name,),
            data_type="int",
        )

        # Update projects to use new customer_id
        if old_customer_id and new_customer_id:
            self.execute_query(
                """
                update projects
                set customer_id = ?
                where customer_id = ?
            """,
                (new_customer_id, old_customer_id),
                self.log_engine.log_msg(
                    "INFO",
                    f"Updated projects {project_list} to use {customer_name} new id: {new_customer_id}",
                )

    def update_customer(
        self,
        customer_name: str,
        new_customer_name: str,
        org_url: str = None,
        pat_token: str = None,
    ):
        self.execute_query(
            """
            update customers
            set
                customer_name = ?,
                org_url = ?,
                pat_token = ?
            where customer_name = ?
        """,
            (new_customer_name, org_url, pat_token, customer_name),
        )

        self.execute_query(
            """
            update time
            set
                customer_name = ?
            where customer_name = ?
        """,
            (new_customer_name, customer_name),
        )

        self.log_engine.log_msg(
            "INFO",
            f"Updated customer name from '{customer_name}' to '{new_customer_name}'",
        )

    def disable_customer(self, customer_name: str):
        self.execute_query(
            """
            update customers
            set is_current = 0
            where customer_name = ?
        """,
            (customer_name,),
        )
        self.log_engine.log_msg("INFO", f"Disabled customer '{customer_name}'")

    def enable_customer(self, customer_name: str):
        self.execute_query(
            """
            update customers
            set is_current = 1  
            where customer_name = ? 
            and valid_to is null
            and customer_id = (
                select customer_id from customers
                where customer_name = ?
                and valid_to is null
                order by datetime(inserted_at) desc
                limit 1
            )
        """,
            (customer_name, customer_name),
        )
        self.log_engine.log_msg("INFO", f"Enabled customer '{customer_name}'")

    ### Project Table Operations ###

    def insert_project(self, customer_name: str, project_name: str, git_id: int = None):
        customer_id = self._get_value_from_db(
            "select customer_id from customers where customer_name = ? and is_current = 1",
            (customer_name,),
            data_type="int",
        )

        existing_projects = self.fetch_query(
            """
            select * from projects
            where project_name = ? and customer_id = ?
        """,
            (project_name, customer_id),
        )

        if not existing_projects.empty and existing_projects["is_current"].iloc[0] == 1:
            self.log_engine.log_msg(
                "WARNING",
                f"Project '{project_name}' for customer '{customer_name}' already exists",
            )
            return
        elif not existing_projects.empty:
            project_id = existing_projects["project_id"].iloc[0]
            self.execute_query(
                "update projects set is_current = 1 where project_id = ?", (project_id,)
            )
            self.log_engine.log_msg(
                "INFO",
                f"Enabled project '{project_name}' for customer '{customer_name}'",
            )
        else:
            self.execute_query(
                """
                insert into projects (customer_id, project_name, is_current, git_id)
                values (?, ?, 1, ?)
            """,
                (customer_id, project_name, git_id),
            )
            self.log_engine.log_msg(
                "INFO",
                f"Inserted new project '{project_name}' for customer '{customer_name}'",
            )

    def update_project(
        self,
        customer_name: str,
        project_name: str,
        new_project_name: str,
        new_git_id: int = None,
    ):
        self.execute_query(
            """
            update projects
            set
                project_name = ?,
                git_id = ?
            where project_name = ? and customer_id = (
                select customer_id from customers where customer_name = ? and is_current = 1
            )
        """,
            (new_project_name, new_git_id, project_name, customer_name),
        )

        self.execute_query(
            """
            update time
            set
                project_name = ?
            where project_name = ? and customer_name = ?
        """,
            (new_project_name, project_name, customer_name),
        )
        self.log_engine.log_msg(
            "INFO", f"Updated project '{project_name}' for customer '{customer_name}'"
        )

    def disable_project(self, customer_name: str, project_name: str):
        self.execute_query(
            """
            update projects
            set is_current = 0
            where project_name = ? and customer_id in (
                select customer_id from customers where customer_name = ? and is_current = 1
            )
        """,
            (project_name, customer_name),
        )
        self.log_engine.log_msg(
            "INFO", f"Disabled project '{project_name}' for customer '{customer_name}'"
        )

    def enable_project(self, customer_name: str, project_name: str):
        self.execute_query(
            """
            update projects
            set is_current = 1
            where project_name = ? and customer_id in (
                select customer_id from customers where customer_name = ?
            )
        """,
            (project_name, customer_name),
        )
        self.log_engine.log_msg(
            "INFO", f"Enabled project '{project_name}' for customer '{customer_name}'"
        )

    ### Bonus Table Operations ###

    def insert_bonus(self, start_date: str, bonus_percent: int) -> None:
        day_before_start_date = (
            datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        self.execute_query(
            f"update bonus set end_date = '{day_before_start_date}' where end_date is Null"
        )
        amount = min(bonus_percent / 100, 1)
        self.execute_query(
            "insert into bonus (start_date, bonus_percent) values (?, ?)",
            (start_date, round(amount, 3)),
        )
        self.log_engine.log_msg(
            "INFO",
            f"Inserted new bonus percent {bonus_percent}% starting from {start_date}",
        )

    ### Query Operations ###

    def get_query_list(self):
        query = """
            select
                query_name,
                query_sql,
                is_default
            from queries
        """
        result = self.fetch_query(query)
        return result

    ### DevOps Operations ###

    def update_devops_data(self, df: pd.DataFrame):
        if df.empty or len(df.columns) == 0:
            self.log_engine.log_msg(
                "WARNING", "No DevOps data to update. Table not created."
            )
            return
        df.to_sql("devops", self.conn, if_exists="replace", index=False)
        self.conn.commit()

    ### UI Operations ###

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
            from customers c
            left join projects p on p.customer_id = c.customer_id
        """
        result = self.fetch_query(query)
        return result

    def get_project_list_from_project_id(self, project_id: int):
        query = """
            select 
                p.project_id, p.project_name
            from projects p
            where p.customer_id in (select customer_id from projects where project_id = ?)
        """
        result = self.fetch_query(query, (project_id,))
        return result

    @staticmethod
    def get_schema_info(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Get tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = set(row[0] for row in cursor.fetchall())
        # Get triggers
        cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger';")
        triggers = set(row[0] for row in cursor.fetchall())
        # Get indexes
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
        indexes = set(row[0] for row in cursor.fetchall())
        # Get columns per table
        columns = {}
        for table in tables:
            cursor.execute(f"PRAGMA table_info('{table}')")
            columns[table] = [row[1] for row in cursor.fetchall()]
        conn.close()
        return {
            "tables": tables,
            "triggers": triggers,
            "indexes": indexes,
            "columns": columns,
        }

    @staticmethod
    def compare_schemas(schema1, schema2):
        result = []
        # Tables
        only_in_1 = schema1["tables"] - schema2["tables"]
        only_in_2 = schema2["tables"] - schema1["tables"]
        if only_in_1:
            result.append(f"Tables only in main DB: {only_in_1}")
        if only_in_2:
            result.append(f"Tables only in uploaded DB: {only_in_2}")
        # Triggers
        trig_1 = schema1["triggers"] - schema2["triggers"]
        trig_2 = schema2["triggers"] - schema1["triggers"]
        if trig_1:
            result.append(f"Triggers only in main DB: {trig_1}")
        if trig_2:
            result.append(f"Triggers only in uploaded DB: {trig_2}")
        # Indexes
        idx_1 = schema1["indexes"] - schema2["indexes"]
        idx_2 = schema2["indexes"] - schema1["indexes"]
        if idx_1:
            result.append(f"Indexes only in main DB: {idx_1}")
        if idx_2:
            result.append(f"Indexes only in uploaded DB: {idx_2}")
        # Columns
        for table in schema1["tables"] & schema2["tables"]:
            cols1 = set(schema1["columns"].get(table, []))
            cols2 = set(schema2["columns"].get(table, []))
            if cols1 != cols2:
                result.append(
                    f"Column difference in table '{table}': main={cols1}, uploaded={cols2}"
                )
        return "\n".join(result) if result else "Schemas are identical!"

    @staticmethod
    def generate_sync_sql(main_db_path, uploaded_db_path):
        conn_main = sqlite3.connect(main_db_path)
        conn_uploaded = sqlite3.connect(uploaded_db_path)
        cursor_main = conn_main.cursor()
        cursor_uploaded = conn_uploaded.cursor()
        sql_statements = []

        # Tables
        cursor_main.execute("select name, sql from sqlite_master where type='table';")
        main_tables = {row[0]: row[1] for row in cursor_main.fetchall()}
        cursor_uploaded.execute("select name from sqlite_master where type='table';")
        uploaded_tables = set(row[0] for row in cursor_uploaded.fetchall())
        missing_tables = set(main_tables.keys()) - uploaded_tables
        for table in missing_tables:
            sql_statements.append(main_tables[table])

        # Columns
        for table in set(main_tables.keys()) & uploaded_tables:
            cursor_main.execute(f"pragma table_info('{table}')")
            main_cols = {row[1]: row for row in cursor_main.fetchall()}
            cursor_uploaded.execute(f"pragma table_info('{table}')")
            uploaded_cols = {row[1]: row for row in cursor_uploaded.fetchall()}
            missing_cols = set(main_cols.keys()) - set(uploaded_cols.keys())
            for col in missing_cols:
                col_type = main_cols[col][2]
                sql_statements.append(
                    f"alter table {table} add column {col} {col_type};"
                )
            # Detect columns with different datatypes
            common_cols = set(main_cols.keys()) & set(uploaded_cols.keys())
            for col in common_cols:
                main_type = main_cols[col][2]
                uploaded_type = uploaded_cols[col][2]
                if main_type.lower() != uploaded_type.lower():
                    sql_statements.append(
                        f"-- WARNING: Column '{col}' in table '{table}' has type '{uploaded_type}' in uploaded DB but '{main_type}' in main DB. Manual review required."
                    )

        # Triggers
        cursor_main.execute("select name, sql from sqlite_master where type='trigger';")
        main_triggers = {row[0]: row[1] for row in cursor_main.fetchall()}
        cursor_uploaded.execute("select name from sqlite_master where type='trigger';")
        uploaded_triggers = set(row[0] for row in cursor_uploaded.fetchall())
        missing_triggers = set(main_triggers.keys()) - uploaded_triggers
        for trigger in missing_triggers:
            sql_statements.append(main_triggers[trigger])

        # Indexes
        cursor_main.execute(
            "select name, sql from sqlite_master where type='index' and sql is not null;"
        )
        main_indexes = {row[0]: row[1] for row in cursor_main.fetchall()}
        cursor_uploaded.execute("select name from sqlite_master where type='index';")
        uploaded_indexes = set(row[0] for row in cursor_uploaded.fetchall())
        missing_indexes = set(main_indexes.keys()) - uploaded_indexes
        for idx in missing_indexes:
            sql_statements.append(main_indexes[idx])

        # Remove extra tables
        extra_tables = uploaded_tables - set(main_tables.keys())
        for table in extra_tables:
            sql_statements.append(f"drop table if exists {table};")

        # Remove extra triggers
        cursor_uploaded.execute("select name from sqlite_master where type='trigger';")
        uploaded_triggers = set(row[0] for row in cursor_uploaded.fetchall())
        extra_triggers = uploaded_triggers - set(main_triggers.keys())
        for trigger in extra_triggers:
            sql_statements.append(f"drop trigger if exists {trigger};")

        # Remove extra indexes
        cursor_uploaded.execute("select name from sqlite_master where type='index';")
        uploaded_indexes = set(row[0] for row in cursor_uploaded.fetchall())
        extra_indexes = uploaded_indexes - set(main_indexes.keys())
        for idx in extra_indexes:
            sql_statements.append(f"drop index if exists {idx};")

        conn_main.close()
        conn_uploaded.close()
        return "\n\n".join(sql_statements) if sql_statements else "-- No changes needed"

    def execute_query(self, query: str, params: tuple = ()):
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
        except Exception as e:
            self.log_engine.log_msg("ERROR", f"Error executing query: {query}\n{e}")
            raise

    def fetch_query(self, query: str, params: tuple = ()):
        try:
            return pd.read_sql(query, self.conn, params=params)
        except Exception as e:
            self.log_engine.log_msg("ERROR", f"Error fetching query: {query}\n{e}")
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
            self.log_engine.log_msg("ERROR", f"Error running query: {query}\n{e}")
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
            self.log_engine.log_msg("ERROR", "Invalid data type specified.")
            raise ValueError("Invalid data type specified.")

    def close(self):
        self.conn.close()
