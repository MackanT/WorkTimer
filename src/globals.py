# pandas removed from globals.py -- use local imports where needed
from .devops import DevOpsManager

# Importing a tracker module registers it (see src/trackers/). Imported after
# devops above — the Azure provider subclasses DevOpsClient, so this order
# avoids a circular import.
from .trackers import azure as _azure_tracker  # noqa: F401
from .trackers import jira as _jira_tracker  # noqa: F401
from .trackers.base import DEFAULT_STATE_OPTIONS, DEFAULT_TYPE_HIERARCHY
from .database import Database
from dataclasses import dataclass
import asyncio
import logging
import datetime
import pandas as pd


# Process-wide Database instances keyed by file name. Every browser tab gets
# its own AppCore/QueryEngine, but they all share ONE SQLite connection per
# file — per-tab connections only added lock contention, and initialize_db()
# (incl. schema auto-migration) now runs once per process instead of per tab.
_shared_databases: dict = {}


def _seconds_until_next(hour: int, now: datetime.datetime | None = None) -> float:
    """Seconds from `now` until the next occurrence of `hour`:00.

    Uses today's occurrence if it hasn't passed yet, otherwise tomorrow's — so
    a scheduler started at 00:30 fires at 02:00, not ~25 h later. Takes an
    optional `now` purely so the math is unit-testable.
    """
    now = now or datetime.datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


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
        if file_name not in _shared_databases:
            db = Database(file_name, log_engine)
            db.initialize_db()
            _shared_databases[file_name] = db
        self.db = _shared_databases[file_name]
        self.df = None
        self.log = log_engine

    async def function_db(self, func_name: str, *args, **kwargs):
        func = getattr(self.db, func_name)
        return await asyncio.to_thread(func, *args, **kwargs)

    async def query_db(self, query: str, params: tuple = ()):
        return await asyncio.to_thread(self.db.smart_query, query, params)

    async def refresh(self):
        self.df = await self.function_db("get_query_list")


class DevOpsEngine:
    def __init__(self, query_engine: QueryEngine, log_engine: logging.Logger):
        self.manager = None
        self.df = None
        self.query_engine = query_engine
        self.log = log_engine
        self._scheduled_tasks = []
        self._scheduled_started = False
        # Serializes update_devops() so a manual sync (settings page) and the
        # hourly scheduled sync can't interleave DB writes.
        self._update_lock = asyncio.Lock()
        self.last_incremental_sync: datetime.datetime | None = None
        self.last_full_sync: datetime.datetime | None = None

    async def start_scheduled_updates(self):
        """Start background tasks for scheduled DevOps updates.

        The engine itself is a process-wide singleton (see app.py), so the
        instance flag is sufficient — the old extra module-level flag is gone.
        """
        if self._scheduled_started:
            self.log.info("Scheduled DevOps tasks already running — skipping")
            return
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
                    await asyncio.sleep(_seconds_until_next(2))
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
        for task in self._scheduled_tasks:
            task.cancel()
        self._scheduled_tasks.clear()
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

    def get_available_projects(self) -> dict:
        """{customer_name: [project names in their org]} for connected customers,
        or {} when no manager. Feeds the customer form's project picker."""
        return self.manager.get_available_projects() if self.manager else {}

    def upload_attachment(self, customer_name, file_name, content):
        """Upload bytes as a DevOps attachment for a customer; returns the URL or
        None. Used to embed pasted/inserted images in work-item descriptions."""
        return (
            self.manager.upload_attachment(customer_name, file_name, content)
            if self.manager
            else None
        )

    def get_work_item_options(self, customer_name: str | None = None):
        """Active DevOps work items for the Git-ID picker.

        With ``customer_name``, returns a flat list of ``{"label", "id"}`` for
        that customer. Without it, returns ``{customer_name: [...]}`` for every
        customer. Empty (list/dict respectively) when DevOps data isn't loaded,
        so callers degrade to manual id entry. Uses the same Active/New filter
        as the timer dialog's work-item selector.
        """
        if self.df is None or self.df.empty:
            return [] if customer_name is not None else {}
        # Provider-neutral "open item" filter — state NAMES differ per tracker
        # (ADO: Active/New..., Jira: To Do/In Progress...), so exclude the
        # done-ish ones instead of whitelisting Azure's.
        active = self.df[~self.df["state"].isin(["Resolved", "Closed", "Removed", "Done"])]
        if customer_name is not None:
            active = active[active["customer_name"] == customer_name]
        # Newest (highest id) first — most likely related to current work.
        active = active.sort_values("id", ascending=False)

        def _row_option(row):
            if pd.isna(row.get("id")) or pd.isna(row.get("display_name")):
                return None
            return {"label": str(row["display_name"]), "id": int(row["id"])}

        if customer_name is not None:
            return [opt for _, r in active.iterrows() if (opt := _row_option(r))]
        result: dict = {}
        for _, r in active.iterrows():
            opt = _row_option(r)
            if opt:
                result.setdefault(r["customer_name"], []).append(opt)
        return result

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
        # A customer's connection comes from its linked tracker; the legacy
        # per-customer columns remain the fallback for unlinked customers
        # (pre-migration rows, or an unfinished setup).
        df = await self.query_engine.function_db("get_tracker_connections")
        # PATs are stored encrypted at rest — providers need the real token.
        # An undecryptable value becomes '' (backup restored without its key),
        # so that customer is skipped with a clear log line.
        if not df.empty:
            from .pat_crypto import decrypt_pat

            df["pat_token"] = df["pat_token"].map(
                lambda v: decrypt_pat(v, self.query_engine.file_name, self.log)
            )
            df = df[df["pat_token"] != ""]
        # DevOpsManager.__init__ connects to every org (network I/O) — keep it
        # off the event loop so the UI stays responsive during startup.
        self.manager = await asyncio.to_thread(DevOpsManager, df, self.log)

    def provider_label(self, customer_name: str | None = None) -> str:
        """The customer's tracker name for UI labels ('Azure DevOps'/'Jira')."""
        if self.manager and customer_name in (self.manager.clients or {}):
            return self.manager.clients[customer_name].display_name
        return "Tracker"

    def capabilities(self, customer_name: str | None = None):
        """The customer's tracker capabilities; permissive defaults when the
        customer has no connected provider (UI then behaves as before)."""
        from .trackers.base import TrackerCapabilities

        if self.manager and customer_name in (self.manager.clients or {}):
            return self.manager.clients[customer_name].capabilities()
        return TrackerCapabilities()

    def state_options(self, customer_name: str | None = None) -> list:
        """State names for a customer's tracker (Jira: its project statuses,
        cached on the provider after the first fetch). May do one blocking
        HTTP call on a cache miss — call via to_thread from async code."""
        if self.manager and customer_name in (self.manager.clients or {}):
            try:
                states = self.manager.clients[customer_name].state_options()
                if states:
                    return list(states)
            except Exception as e:
                self.log.error(f"State options failed for {customer_name}: {e}")
        return list(DEFAULT_STATE_OPTIONS)

    def preferred_type(self, customer_name: str | None = None) -> str:
        """The default board level for a customer's tracker (User Story for
        DevOps, Story for Jira — its Sub-task leaf is auxiliary)."""
        if self.manager:
            if customer_name and customer_name in self.manager.clients:
                return self.manager.clients[customer_name].preferred_type()
            for client in self.manager.clients.values():
                return client.preferred_type()
        return DEFAULT_TYPE_HIERARCHY[-1]

    def type_hierarchy(self, customer_name: str | None = None) -> tuple:
        """Work-item levels root → leaf for a customer's tracker (falls back to
        the default hierarchy when no provider is connected). UI code should
        consume this instead of hard-coding Epic/Feature/User Story."""
        if self.manager:
            if customer_name and customer_name in self.manager.clients:
                return self.manager.clients[customer_name].type_hierarchy()
            for client in self.manager.clients.values():
                return client.type_hierarchy()
        return DEFAULT_TYPE_HIERARCHY

    async def update_devops(self, incremental: bool = False):
        if not self.manager:
            self.log.warning("No DevOps connections available")
            return None

        async with self._update_lock:
            await self._update_devops_locked(incremental)

    async def _update_devops_locked(self, incremental: bool):
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

        # Blocking Azure DevOps API traffic — run in a worker thread so the
        # scheduled hourly sync doesn't freeze the UI for all clients.
        status, devops_df = await asyncio.to_thread(
            self.manager.get_epics_feature_df,
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
        # Current customers only — a disabled customer's cached items stay
        # in the table but disappear from the board/pickers until re-enabled.
        df = await self.query_engine.function_db("get_visible_devops_items")
        self.df = df if not df.empty else None
        if self.df is None:
            self.log.warning("DevOps dataframe is empty")
        else:
            self.df["display_name"] = self.df.apply(
                lambda row: f"{row['type']}: {int(row['id'])} - {row['title']}", axis=1
            )
            self.log.info(f"DevOps dataframe loaded with {len(self.df)} rows")

