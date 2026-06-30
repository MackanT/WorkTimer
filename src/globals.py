# pandas removed from globals.py -- use local imports where needed
from .devops import DevOpsManager
from .database import Database
from dataclasses import dataclass
import asyncio
import logging
import datetime


# Module-level flag: only one DevOpsEngine may ever run scheduled refresh tasks.
# Prevents duplicate tasks when multiple browser tabs reconnect simultaneously.
_devops_scheduled_started: bool = False


@dataclass
class SaveData:
    function: str
    main_action: str
    main_param: str
    secondary_action: str
    button_name: str = "Save"


class QueryEngine:
    def __init__(self, file_name: str, log_engine: logging.Logger):
        self.file_name = file_name
        self.db = Database(file_name, log_engine)
        self.db.initialize_db()
        self.df = None
        self.log = log_engine

    async def function_db(self, func_name: str, *args, **kwargs):
        func = getattr(self.db, func_name)
        return await asyncio.to_thread(func, *args, **kwargs)

    async def query_db(self, query: str, params: tuple = ()):
        return await asyncio.to_thread(self.db.smart_query, query, params)

    async def refresh(self):
        self.df = await self.function_db("get_query_list")


class AddData:
    def __init__(self, query_engine: QueryEngine, log_engine: logging.Logger):
        self.df = None
        self.query_engine = query_engine
        self.log = log_engine

    async def refresh(self):
        self.df = await self.query_engine.function_db("get_data_input_list")


class DevOpsEngine:
    def __init__(self, query_engine: QueryEngine, log_engine: logging.Logger):
        self.manager = None
        self.df = None
        self.query_engine = query_engine
        self.log = log_engine
        self._scheduled_tasks = []
        self._scheduled_started = False
        self.last_incremental_sync: datetime.datetime | None = None
        self.last_full_sync: datetime.datetime | None = None

    async def start_scheduled_updates(self):
        """Start background tasks for scheduled DevOps updates (called once globally)."""
        global _devops_scheduled_started
        if _devops_scheduled_started or self._scheduled_started:
            self.log.info("Scheduled DevOps tasks already running — skipping")
            return
        _devops_scheduled_started = True
        self._scheduled_started = True
        self.log.info("Starting scheduled DevOps update tasks")

        # Hourly incremental update
        async def hourly_incremental():
            while True:
                try:
                    await asyncio.sleep(3600)
                    self.log.info("Running scheduled incremental DevOps update")
                    await self.update_devops(incremental=True)
                except Exception as e:
                    self.log.error(f"Error in incremental DevOps update: {e}")
                except asyncio.CancelledError:
                    break

        # Daily full refresh at 2 AM
        async def daily_full_refresh():
            while True:
                try:
                    # Calculate seconds until 2 AM
                    tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
                    target = tomorrow.replace(hour=2, minute=0, second=0, microsecond=0)
                    seconds_until_2am = (
                        target - datetime.datetime.now()
                    ).total_seconds()

                    await asyncio.sleep(seconds_until_2am)
                    self.log.info("Running scheduled daily full refresh")
                    await self.update_devops(incremental=False)
                    # Loop back immediately — next iteration recalculates time until 2 AM
                except Exception as e:
                    self.log.error(f"Error in daily full refresh: {e}")
                    await asyncio.sleep(3600)  # Wait 1 hour before retrying
                except asyncio.CancelledError:
                    break

        # Start both tasks
        task1 = asyncio.create_task(hourly_incremental())
        task2 = asyncio.create_task(daily_full_refresh())
        self._scheduled_tasks.extend([task1, task2])

    def stop_scheduled_updates(self):
        """Stop all scheduled update tasks."""
        global _devops_scheduled_started
        for task in self._scheduled_tasks:
            task.cancel()
        self._scheduled_tasks.clear()
        _devops_scheduled_started = False
        self._scheduled_started = False

    def has_customer_connection(self, customer_name: str) -> bool:
        """
        Check if a specific customer has DevOps integration configured.

        Args:
            customer_name: Name of the customer to check

        Returns:
            True if customer has active DevOps connection
        """
        return bool(self.manager and customer_name in self.manager.clients)

    async def initialize(self):
        """Initialize DevOps connections and data (without starting scheduled tasks)."""
        try:
            await self.setup_manager()

            if not self.manager.clients:
                self.log.warning(
                    "No customers with DevOps credentials. Skipping devops table generation.",
                )
                return

            # Always update/rebuild devops data to reflect latest customer info
            self.log.info("Performing incremental DevOps update on startup.")
            await self.update_devops(incremental=True)
            await self.load_df()
            self.log.info("DevOps preload complete.")

        except Exception as e:
            self.log.error(f"Error during DevOps preload: {e}")

    async def initialize_scheduled_tasks(self):
        """Initialize scheduled tasks after NiceGUI startup (separate from data initialization)."""
        try:
            self.log.info("Initializing DevOps scheduled tasks after app startup")
            await self.start_scheduled_updates()
        except Exception as e:
            self.log.error(f"Error starting DevOps scheduled tasks: {e}")

    async def setup_manager(self):
        df = await self.query_engine.query_db(
            "select distinct customer_name, pat_token, org_url from customers where pat_token is not null and pat_token != '' and org_url is not null and org_url != '' and is_current = 1"
        )
        self.manager = DevOpsManager(df, self.log)

    async def update_devops(self, incremental: bool = False):
        if not self.manager:
            self.log.warning("No DevOps connections available")
            return None

        max_ids = None
        changed_dates = None
        if incremental:
            self.log.info("Performing incremental update of devops data")
            max_id_df = await self.query_engine.query_db(
                "select customer_name, max(id) as max_id, max(changed_date) as max_changed_date from devops group by customer_name"
            )
            if not max_id_df.empty:
                max_ids = dict(
                    zip(max_id_df["customer_name"], max_id_df["max_id"].astype(int))
                )
                # Track max changed_date per customer to catch external edits
                changed_dates = {
                    row["customer_name"]: row["max_changed_date"]
                    for _, row in max_id_df.iterrows()
                    if row["max_changed_date"]
                }
                self.log.info(
                    f"Performing incremental refresh with max IDs per customer: {max_ids}",
                )
            else:
                self.log.warning(
                    "No existing devops data found, performing full refresh"
                )
                incremental = False
        else:
            self.log.info("Getting latest devops data (full refresh)")

        status, devops_df = self.manager.get_epics_feature_df(
            max_ids=max_ids if incremental else None,
            changed_dates=changed_dates if incremental else None,
        )

        if status:
            if incremental and not devops_df.empty:
                self.log.info(f"Merging {len(devops_df)} devops records (new + edited)")
                await self.query_engine.function_db(
                    "update_devops_data", df=devops_df, mode="merge"
                )
                user_msg = (
                    f"DevOps refresh complete — merged {len(devops_df)} records"
                )
            elif incremental and devops_df.empty:
                self.log.info("No new or changed devops records")
                user_msg = "DevOps refresh complete — no new records"
            else:
                await self.query_engine.function_db(
                    "update_devops_data", df=devops_df, mode="replace"
                )
                user_msg = (
                    f"DevOps full refresh complete — loaded {len(devops_df)} records"
                )

            await self.load_df()

            # Record sync timestamps
            if incremental:
                self.last_incremental_sync = datetime.datetime.now()
            else:
                self.last_full_sync = datetime.datetime.now()

            self.log.info(f"DevOps update result: {user_msg}")
        else:
            self.log.error(f"Error when updating the devops data: {devops_df}")

    async def load_df(self):
        df = await self.query_engine.query_db("select * from devops")
        self.df = df if not df.empty else None
        if self.df is None:
            self.log.warning("DevOps dataframe is empty")
        else:
            self.df["display_name"] = self.df.apply(
                lambda row: f"{row['type']}: {int(row['id'])} - {row['title']}", axis=1
            )
            self.log.info(f"DevOps dataframe loaded with {len(self.df)} rows")

    def devops_helper(self, func_name: str, customer_name: str, *args, **kwargs):
        if not self.manager:
            self.log.warning("No DevOps connections available")
            return None

        status = False
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
        elif func_name == "create_user_story":
            status, msg = self.manager.create_user_story(
                customer_name=customer_name,
                title=kwargs.get("title"),
                description=kwargs.get("description"),
                additional_fields=kwargs.get("additional_fields"),
                markdown=kwargs.get("markdown", False),
                parent=kwargs.get("parent"),
            )
            # Note: DevOps refresh is handled by on_success_callback in the UI
        elif func_name == "create_epic":
            status, msg = self.manager.create_epic(
                customer_name=customer_name,
                title=kwargs.get("title"),
                description=kwargs.get("description"),
                additional_fields=kwargs.get("additional_fields"),
                markdown=kwargs.get("markdown", False),
            )
            # Note: DevOps refresh is handled by on_success_callback in the UI
        elif func_name == "create_feature":
            status, msg = self.manager.create_feature(
                customer_name=customer_name,
                title=kwargs.get("title"),
                description=kwargs.get("description"),
                additional_fields=kwargs.get("additional_fields"),
                markdown=kwargs.get("markdown", False),
                parent=kwargs.get("parent"),
            )
            # Note: DevOps refresh is handled by on_success_callback in the UI

        else:
            self.log.warning(f"Unknown DevOps function: {func_name}")
            return False, f"Unknown DevOps function: {func_name}"

        if not status:
            self.log.error(msg)
        return status, msg
