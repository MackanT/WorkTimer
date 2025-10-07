import pandas as pd
from devops_new import DevOpsManager
from database_new import Database
import asyncio
import logging


def generate_sync_sql(main_db, uploaded_path):
    return Database.generate_sync_sql(main_db, uploaded_path)


class LogData:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.logger, self.formatter = self.setup_logging()

        self.LOG_BUFFER = []
        self.LOG_TEXTAREA = None
        self.LOG_COLORS = {
            "INFO": "white",
            "WARNING": "orange",
            "ERROR": "red",
        }

    def setup_logging(self):
        LOGFORMAT = "%(asctime)s | %(levelname)-8s | %(name).35s :: %(message)s"
        formatter = logging.Formatter(fmt=LOGFORMAT, datefmt="%Y-%m-%d %H:%M:%S")
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger = logging.getLogger("WorkTimer")
        logger.setLevel(logging.DEBUG if self.debug else logging.INFO)
        logger.addHandler(handler)
        return logger, formatter

    def log_msg(self, level="INFO", msg=""):
        level = level.upper()
        # Always print to terminal
        getattr(self.logger, level.lower(), self.logger.info)(msg)

        # Format for web log using the same formatter
        record = logging.LogRecord(
            name=self.logger.name,
            level=getattr(logging, level, logging.INFO),
            pathname=__file__,
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )
        formatted = self.formatter.format(record)
        # Only add DEBUG to web log if debug==True; all other levels always added
        self.LOG_BUFFER.append({"level": level, "msg": formatted})
        if self.LOG_TEXTAREA:
            self.update_log_textarea()

    def update_log_textarea(self):
        if self.LOG_TEXTAREA:
            lines = []
            for entry in self.LOG_BUFFER:
                color = self.LOG_COLORS.get(entry["level"], "white")
                # Use HTML for color
                line = f'<span style="color:{color};"> {entry["msg"]}</span>'
                lines.append(line)
            self.LOG_TEXTAREA.set_content("<br>".join(lines))
            self.LOG_TEXTAREA.update()
            # Scroll to bottom using run_method
            self.LOG_TEXTAREA.run_method("scrollTo", 0, 99999)


class QueryData:
    def __init__(self, file_name: str, log_engine: LogData):
        self.file_name = file_name
        self.db = Database(file_name)
        self.db.initialize_db()
        self.df = None
        self.log = log_engine

    async def function_db(self, func_name: str, *args, **kwargs):
        func = getattr(self.db, func_name)
        return await asyncio.to_thread(func, *args, **kwargs)

    async def query_db(self, query: str):
        return await asyncio.to_thread(self.db.smart_query, query)

    async def refresh(self):
        self.df = await self.function_db("get_query_list")


class AddData:
    def __init__(self, query_engine: QueryData, log_engine: LogData):
        self.df = None
        self.query_engine = query_engine
        self.log = log_engine

    async def refresh(self):
        self.df = await self.query_engine.function_db("get_data_input_list")


class DevopsData:
    def __init__(self, query_engine: QueryData, log_engine: LogData):
        self.manager = None
        self.df = None
        self.long_df = None
        self.query_engine = query_engine
        self.log = log_engine

    async def initialize(self):
        try:
            await self.setup_manager()
            await self.load_df()
            self.log.log_msg("INFO", "DevOps preload complete.")
        except Exception as e:
            self.log.log_msg("ERROR", f"Error during DevOps preload: {e}")

    async def setup_manager(self):
        df = await self.query_engine.query_db(
            "select distinct customer_name, pat_token, org_url from customers where pat_token is not null and pat_token != '' and org_url is not null and org_url != '' and is_current = 1"
        )
        self.manager = DevOpsManager(df)

    async def update_devops(self):
        if not self.manager:
            self.log.log_msg("WARNING", "No DevOps connections available")
            return None
        self.log.log_msg("INFO", "Getting latest devops data")
        status, devops_df = self.manager.get_epics_feature_df()
        if status:
            await self.query_engine.function_db("update_devops_data", df=devops_df)
        else:
            self.log.log_msg(
                "ERROR", f"Error when updating the devops data: {devops_df}"
            )

    async def load_df(self):
        df = await self.query_engine.query_db("select * from devops")
        self.df = df if not df.empty else None
        if self.df is None or self.df.empty:
            self.log.log_msg("WARNING", "DevOps dataframe is empty")
        else:
            self._get_long_df()
            self.log.log_msg(
                "INFO", f"DevOps dataframe loaded with {len(self.df)} rows"
            )
            # TODO add some date when it was last collected

    def _get_long_df(self):
        if self.df is None or self.df.empty:
            return None
        records = []
        for _, row in self.df.iterrows():
            if pd.notna(row.get("epic_id")):
                records.append(
                    {
                        "customer_name": row["customer_name"],
                        "type": "Epic",
                        "id": int(row["epic_id"]),
                        "title": row["epic_title"],
                        "state": row["epic_state"],
                        "name": f"Epic: {int(row['epic_id'])} - {row['epic_title']}",
                        "parent_id": None,
                    }
                )
            if pd.notna(row.get("feature_id")):
                records.append(
                    {
                        "customer_name": row["customer_name"],
                        "type": "Feature",
                        "id": int(row["feature_id"]),
                        "title": row["feature_title"],
                        "state": row["feature_state"],
                        "name": f"Feature: {int(row['feature_id'])} - {row['feature_title']}",
                        "parent_id": int(row["epic_id"])
                        if pd.notna(row.get("epic_id"))
                        else None,
                    }
                )
            if pd.notna(row.get("user_story_id")):
                records.append(
                    {
                        "customer_name": row["customer_name"],
                        "type": "User Story",
                        "id": int(row["user_story_id"]),
                        "title": row["user_story_title"],
                        "state": row["user_story_state"],
                        "name": f"User Story: {int(row['user_story_id'])} - {row['user_story_title']}",
                        "parent_id": int(row["feature_id"])
                        if pd.notna(row.get("feature_id"))
                        else None,
                    }
                )
        long_df = pd.DataFrame(records)
        self.long_df = long_df[
            long_df["state"].isin(["New", "Active"])
        ].drop_duplicates()

    def devops_helper(self, func_name: str, customer_name: str, *args, **kwargs):
        if not self.manager:
            self.log.log_msg("WARNING", "No DevOps connections available")
            return None
        msg = None
        if func_name == "save_comment":
            status, msg = self.manager.save_comment(
                customer_name=customer_name,
                comment=kwargs.get("comment"),
                git_id=int(kwargs.get("git_id")),
            )
        elif func_name == "get_workitem_level":
            git_id_raw = kwargs.get("git_id")
            status, msg = self.manager.get_workitem_level(
                customer_name=customer_name,
                work_item_id=int(git_id_raw) if str(git_id_raw).isnumeric() else None,
                level=kwargs.get("level"),
            )
        if not status:
            self.log.log_msg("ERROR", msg)
        return status, msg
