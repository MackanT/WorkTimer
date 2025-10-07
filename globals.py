import pandas as pd
from devops_new import DevOpsManager
from database_new import Database
import asyncio


class QueryData:
    def __init__(self, file_name: str):
        self.file_name = file_name
        self.db = Database(file_name)
        self.db.initialize_db()
        self.df = None

    async def function_db(self, func_name: str, *args, **kwargs):
        func = getattr(self.db, func_name)
        return await asyncio.to_thread(func, *args, **kwargs)

    async def query_db(self, query: str):
        return await asyncio.to_thread(self.db.smart_query, query)

    async def refresh(self):
        self.df = await self.function_db("get_query_list")


class AddData:
    def __init__(self, query_engine: QueryData):
        self.df = None
        self.query_engine = query_engine

    async def refresh(self):
        self.df = await self.query_engine.function_db("get_data_input_list")


class DevopsData:
    def __init__(self, query_engine: QueryData):
        self.manager = None
        self.df = None
        self.long_df = None
        self.query_engine = query_engine

        self.log = []

    async def initialize(self):
        try:
            await self.setup_manager()
            await self.load_df()
            self.log.append(("INFO", "DevOps preload complete."))
        except Exception as e:
            self.log.append(("ERROR", f"Error during DevOps preload: {e}"))

    async def setup_manager(self):
        df = await self.query_engine.query_db(
            "select distinct customer_name, pat_token, org_url from customers where pat_token is not null and pat_token != '' and org_url is not null and org_url != '' and is_current = 1"
        )
        self.manager = DevOpsManager(df)

    async def update_devops(self):
        if not self.manager:
            self.log.append(("WARNING", "No DevOps connections available"))
            return None
        self.log.append(("INFO", "Getting latest devops data"))
        status, devops_df = self.manager.get_epics_feature_df()
        if status:
            await self.query_engine.function_db("update_devops_data", df=devops_df)
        else:
            self.log.append(
                ("ERROR", f"Error when updating the devops data: {devops_df}")
            )

    async def load_df(self):
        df = await self.query_engine.query_db("select * from devops")
        self.df = df if not df.empty else None
        if self.df is None or self.df.empty:
            self.log.append(("WARNING", "DevOps dataframe is empty"))
        else:
            self._get_long_df()
            self.log.append(
                ("INFO", f"DevOps dataframe loaded with {len(self.df)} rows")
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
            self.log.append(("WARNING", "No DevOps connections available"))
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
            self.log.append(("ERROR", msg))
        return status, msg
