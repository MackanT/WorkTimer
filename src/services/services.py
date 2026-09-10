"""
Service Layer

Thin wrappers around engines for UI-triggered operations.
All user feedback goes through the event bus.

Note: the old DatabaseService/TimerService scaffolding was removed — it queried
tables and methods that don't exist and had no callers. The DevOps refreshes no
longer need a worker thread either: DevOpsEngine.update_devops() runs its
blocking API traffic via asyncio.to_thread internally, so awaiting it on the
main loop keeps the UI responsive.
"""

from ..core.app import AppCore


class BaseService:
    """Base class for all services: holds core, logger, and event bus."""

    def __init__(self, core: AppCore):
        self.core = core
        self.logger = core.logger
        self.event_bus = core.event_bus


class DevOpsService(BaseService):
    """Azure DevOps sync operations with user feedback."""

    async def refresh_incremental(self):
        """Run an incremental DevOps refresh. Notifies on start and completion."""
        if not self.core.devops_engine:
            self.event_bus.notify("No tracker configured", type_="warning")
            return
        try:
            self.event_bus.notify("Starting tracker incremental refresh...", type_="info")
            await self.core.devops_engine.update_devops(incremental=True)
            self.event_bus.notify("Tracker refresh completed successfully!", type_="positive")
            self.event_bus.emit("devops_refreshed")
        except Exception as e:
            self.logger.error(f"DevOps refresh failed: {e}")
            self.event_bus.notify(f"Tracker refresh failed: {e}", type_="negative")

    async def refresh_full(self):
        """Run a full DevOps refresh (can take minutes for large orgs)."""
        if not self.core.devops_engine:
            self.event_bus.notify("No tracker configured", type_="warning")
            return
        try:
            self.event_bus.notify(
                "Starting FULL tracker refresh (this may take several minutes)...",
                type_="warning",
            )
            await self.core.devops_engine.update_devops(incremental=False)
            self.event_bus.notify("Full tracker refresh completed successfully!", type_="positive")
            self.event_bus.emit("devops_refreshed")
        except Exception as e:
            self.logger.error(f"Full DevOps refresh failed: {e}")
            self.event_bus.notify(f"Full tracker refresh failed: {e}", type_="negative")
