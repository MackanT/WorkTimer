import pandas as pd
from .devops import DevOpsManager
from .database import Database
from dataclasses import dataclass
import asyncio
import logging
import datetime


# Global registry for shared instances
class GlobalRegistry:
    """Registry for shared application instances."""

    _instances = {}

    @classmethod
    def set(cls, name: str, instance):
        """Set a global instance."""
        cls._instances[name] = instance

    @classmethod
    def get(cls, name: str, default=None):
        """Get a global instance."""
        return cls._instances.get(name, default)

    @classmethod
    def clear(cls):
        """Clear all instances."""
        cls._instances.clear()


def generate_sync_sql(main_db, uploaded_path):
    return Database.generate_sync_sql(main_db, uploaded_path)


@dataclass
class SaveData:
    function: str
    main_action: str
    main_param: str
    secondary_action: str
    button_name: str = "Save"


@dataclass
class DevOpsTag:
    name: str = ""
    icon: str = "bookmark"
    color: str = "green"


class Logger:
    LOGGERS = {}
    LOG_BUFFER = []
    LOG_TEXTAREA = None
    LOG_COLORS = {
        "INFO": "white",
        "WARNING": "orange",
        "ERROR": "red",
    }

    def __init__(self, name="WorkTimer", debug=False):
        self.name = name
        self.debug = debug
        self.logger, self.formatter = self.setup_logging(name)

    @classmethod
    def get_logger(cls, name="WorkTimer", debug=False):
        if name not in cls.LOGGERS:
            cls.LOGGERS[name] = cls(name=name, debug=debug)
        return cls.LOGGERS[name]

    @classmethod
    def set_log_textarea(cls, textarea):
        cls.LOG_TEXTAREA = textarea
        # Update all loggers' LOG_TEXTAREA reference
        for logger in cls.LOGGERS.values():
            logger.LOG_TEXTAREA = textarea

    def setup_logging(self, name):
        LOGFORMAT = "%(asctime)s | %(levelname)-8s | %(name)-9s :: %(message)s"
        formatter = logging.Formatter(fmt=LOGFORMAT, datefmt="%Y-%m-%d %H:%M:%S")
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG if self.debug else logging.INFO)
        if not logger.hasHandlers():
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
        self.__class__.LOG_BUFFER.append({"level": level, "msg": formatted})
        if self.__class__.LOG_TEXTAREA:
            self.update_log_textarea()

    def update_log_textarea(self):
        if not self.__class__.LOG_TEXTAREA:
            return

        # If the UI element supports push/clear (NiceGUI ui.log), use that
        elem = self.__class__.LOG_TEXTAREA
        try:
            if hasattr(elem, "push"):
                # Clear existing entries then push buffered lines
                if hasattr(elem, "clear"):
                    try:
                        elem.clear()
                    except Exception:
                        pass

                for entry in self.__class__.LOG_BUFFER:
                    color = self.__class__.LOG_COLORS.get(entry["level"], "white")
                    classes = f"text-{color}" if color else None
                    try:
                        # push handles plain text and optional classes for styling
                        if classes:
                            elem.push(entry["msg"], classes=classes)
                        else:
                            elem.push(entry["msg"])
                    except Exception:
                        # If push fails, fall back to setting html content
                        pass
                try:
                    elem.update()
                except Exception:
                    pass
                return
        except Exception:
            # If anything went wrong using ui.log API, continue to fallback
            pass

        # Fallback for textarea-like elements with set_content
        try:
            lines = []
            for entry in self.__class__.LOG_BUFFER:
                color = self.__class__.LOG_COLORS.get(entry["level"], "white")
                line = f'<span style="color:{color}; font-family:monospace; white-space:pre;">{entry["msg"]}</span>'
                lines.append(line)
            # older widgets expose set_content/update
            if hasattr(elem, "set_content"):
                elem.set_content("<br>".join(lines))
            if hasattr(elem, "update"):
                elem.update()
        except Exception:
            # Ignore errors to avoid breaking logging
            pass


class QueryEngine:
    def __init__(self, file_name: str, log_engine: Logger):
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
    def __init__(self, query_engine: QueryEngine, log_engine: Logger):
        self.df = None
        self.query_engine = query_engine
        self.log = log_engine

    async def refresh(self):
        self.df = await self.query_engine.function_db("get_data_input_list")


class DevOpsEngine:
    def __init__(self, query_engine: QueryEngine, log_engine: Logger):
        self.manager = None
        self.df = None
        self.query_engine = query_engine
        self.log = log_engine
        self._scheduled_tasks = []

    async def start_scheduled_updates(self):
        """Start background tasks for scheduled DevOps updates."""
        self.log.log_msg("INFO", "Starting scheduled DevOps update tasks")

        # Hourly incremental update
        async def hourly_incremental():
            while True:
                try:
                    await asyncio.sleep(3600)
                    self.log.log_msg(
                        "INFO", "Running scheduled incremental DevOps update"
                    )
                    await self.update_devops(incremental=True)
                except Exception as e:
                    self.log.log_msg(
                        "ERROR", f"Error in incremental DevOps update: {e}"
                    )
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
                    self.log.log_msg("INFO", "Running scheduled daily full refresh")
                    await self.update_devops(incremental=False)
                    await asyncio.sleep(86400)  # Sleep for rest of day
                except Exception as e:
                    self.log.log_msg("ERROR", f"Error in daily full refresh: {e}")
                    await asyncio.sleep(3600)  # Wait 1 hour before retrying
                except asyncio.CancelledError:
                    break

        # Start both tasks
        task1 = asyncio.create_task(hourly_incremental())
        task2 = asyncio.create_task(daily_full_refresh())
        self._scheduled_tasks.extend([task1, task2])

    def stop_scheduled_updates(self):
        """Stop all scheduled update tasks."""
        for task in self._scheduled_tasks:
            task.cancel()
        self._scheduled_tasks.clear()

    def has_customer_connection(self, customer_name: str) -> bool:
        """
        Check if a specific customer has DevOps integration configured.

        Args:
            customer_name: Name of the customer to check

        Returns:
            True if customer has active DevOps connection
        """
        return bool(
            self.manager
            and hasattr(self.manager, "clients")
            and customer_name in self.manager.clients
        )

    async def initialize(self):
        """Initialize DevOps connections and data (without starting scheduled tasks)."""
        try:
            await self.setup_manager()

            if not getattr(self.manager, "clients", None) or self.manager.clients == {}:
                self.log.log_msg(
                    "WARNING",
                    "No customers with DevOps credentials. Skipping devops table generation.",
                )
                return

            # Always update/rebuild devops data to reflect latest customer info
            self.log.log_msg("INFO", "Performing incremental DevOps update on startup.")
            await self.update_devops(incremental=True)
            await self.load_df()
            self.log.log_msg("INFO", "DevOps preload complete.")

        except Exception as e:
            self.log.log_msg("ERROR", f"Error during DevOps preload: {e}")

    async def initialize_scheduled_tasks(self):
        """Initialize scheduled tasks after NiceGUI startup (separate from data initialization)."""
        try:
            self.log.log_msg(
                "INFO", "Initializing DevOps scheduled tasks after app startup"
            )
            await self.start_scheduled_updates()
        except Exception as e:
            self.log.log_msg("ERROR", f"Error starting DevOps scheduled tasks: {e}")

    async def setup_manager(self):
        df = await self.query_engine.query_db(
            "select distinct customer_name, pat_token, org_url from customers where pat_token is not null and pat_token != '' and org_url is not null and org_url != '' and is_current = 1"
        )
        self.manager = DevOpsManager(df, self.log)

    async def update_devops(self, incremental: bool = False):
        if not self.manager:
            self.log.log_msg("WARNING", "No DevOps connections available")
            return None

        max_ids = None
        if incremental:
            self.log.log_msg("INFO", "Performing incremental update of devops data")
            max_id_df = await self.query_engine.query_db(
                "select customer_name, max(id) as max_id from devops group by customer_name"
            )
            if not max_id_df.empty:
                max_ids = dict(
                    zip(max_id_df["customer_name"], max_id_df["max_id"].astype(int))
                )
                self.log.log_msg(
                    "INFO",
                    f"Performing incremental refresh with max IDs per customer: {max_ids}",
                )
            else:
                self.log.log_msg(
                    "WARNING", "No existing devops data found, performing full refresh"
                )
                incremental = False
        else:
            self.log.log_msg("INFO", "Getting latest devops data (full refresh)")
            # TODO add some date when it was last collected

        status, devops_df = self.manager.get_epics_feature_df(
            max_ids=max_ids if incremental else None
        )

        if status:
            if incremental and not devops_df.empty:
                self.log.log_msg(
                    "INFO", f"Appending {len(devops_df)} new devops records"
                )
                await self.query_engine.function_db(
                    "update_devops_data", df=devops_df, mode="append"
                )
            elif incremental and devops_df.empty:
                self.log.log_msg("INFO", "No new devops records to append")
            else:
                await self.query_engine.function_db(
                    "update_devops_data", df=devops_df, mode="replace"
                )

            await self.load_df()
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
            self.df["display_name"] = self.df.apply(
                lambda row: f"{row['type']}: {int(row['id'])} - {row['title']}", axis=1
            )
            self.log.log_msg(
                "INFO", f"DevOps dataframe loaded with {len(self.df)} rows"
            )

    def devops_helper(self, func_name: str, customer_name: str, *args, **kwargs):
        if not self.manager:
            self.log.log_msg("WARNING", "No DevOps connections available")
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

        if not status:
            self.log.log_msg("ERROR", msg)
        return status, msg


class UIRefreshEngine:
    """Engine for handling UI refresh tasks and active timer detection."""

    def __init__(self, query_engine: QueryEngine, log_engine: Logger):
        self.query_engine = query_engine
        self.log = log_engine
        self._refresh_tasks = []
        self._ui_refresh_callback = None
        self._tab_indicator_callback = None
        self._active_timers_count = 0

    def set_ui_refresh_callback(self, callback):
        """Set the callback function to refresh the Time Tracking UI."""
        self._ui_refresh_callback = callback

    def set_tab_indicator_callback(self, callback):
        """Set the callback function to update the tab indicator."""
        self._tab_indicator_callback = callback

    async def start_ui_refresh(self):
        """Start the UI refresh task."""
        self.log.log_msg("INFO", "Starting UI refresh task")

        async def ui_refresh_loop():
            while True:
                try:
                    await asyncio.sleep(30)  # Refresh every 30 seconds

                    # Check for active timers
                    active_count = await self._check_active_timers()

                    # Update tab indicator if count changed
                    if active_count != self._active_timers_count:
                        self._active_timers_count = active_count
                        if self._tab_indicator_callback:
                            self._tab_indicator_callback(active_count > 0)

                    # Refresh UI if callback is set
                    if self._ui_refresh_callback:
                        await self._ui_refresh_callback()

                except Exception as e:
                    self.log.log_msg("ERROR", f"Error in UI refresh loop: {e}")
                except asyncio.CancelledError:
                    break

        task = asyncio.create_task(ui_refresh_loop())
        self._refresh_tasks.append(task)

    async def _check_active_timers(self):
        """Check how many active timers are running."""
        try:
            df = await self.query_engine.query_db(
                "SELECT COUNT(*) as count FROM time WHERE end_time IS NULL"
            )
            count = df.iloc[0]["count"] if not df.empty else 0
            return count
        except Exception as e:
            self.log.log_msg("ERROR", f"Error checking active timers: {e}")
            return 0

    def stop_ui_refresh(self):
        """Stop all UI refresh tasks."""
        for task in self._refresh_tasks:
            task.cancel()
        self._refresh_tasks.clear()
