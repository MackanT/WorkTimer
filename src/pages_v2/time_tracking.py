"""
Time Tracking Page - Refactored V2

Demonstrates the skeleton/populate pattern with event-driven updates.

Pattern:
1. create_skeleton() - Builds empty page structure
2. populate_page() - Fills page with data (called via event)
3. Worker threads notify via event_bus.notify()
"""

from nicegui import ui, app
from ..core import AppCore, get_config_loader
from ..services import DatabaseService, TimerService
from typing import Optional


# Page-level containers (references to UI elements)
class PageContainers:
    """Holds references to UI containers for updates."""

    active_timers_container: Optional[ui.column] = None
    customer_select: Optional[ui.select] = None
    project_select: Optional[ui.select] = None


@ui.page("/")
async def time_tracking_page():
    """
    Main time tracking page.

    Uses the skeleton → populate → notify pattern.
    Each client gets their own isolated state via AppCore.
    """
    # Get or create app core for this client
    core = AppCore.get_or_create(config_loader=get_config_loader())

    # Initialize engines if this is the first page load
    if not core._initialized:
        await core.initialize_engines()

    # Create services
    db_service = DatabaseService(core)
    timer_service = TimerService(core)

    # Container references
    containers = PageContainers()

    # ============== SKELETON CREATION ==============

    ui.page_title("WorkTimer - Time Tracking")

    # Dark mode
    dark = ui.dark_mode()
    dark.enable()

    with ui.header().classes("items-center justify-between"):
        ui.label("WorkTimer").classes("text-2xl")
        ui.button("Refresh DevOps", icon="refresh", on_click=lambda: refresh_devops())

    with ui.column().classes("w-full p-4 gap-4"):
        # Active timers section
        ui.label("Active Timers").classes("text-xl")
        with ui.column().classes("w-full gap-2") as active_timers:
            containers.active_timers_container = active_timers
            # Initially empty - will be populated
            with ui.card().classes("w-full"):
                ui.spinner(size="lg")
                ui.label("Loading active timers...")

        ui.separator()

        # Start timer section
        ui.label("Start New Timer").classes("text-xl")
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full gap-4"):
                # Customer select (empty initially)
                containers.customer_select = ui.select(
                    label="Customer",
                    options={},
                    with_input=True,
                ).classes("flex-grow")

                # Project select (empty initially)
                containers.project_select = ui.select(
                    label="Project",
                    options={},
                    with_input=True,
                ).classes("flex-grow")

                ui.button(
                    "Start Timer",
                    icon="play_arrow",
                    on_click=lambda: start_timer_clicked(),
                ).props("color=positive")

    # ============== EVENT HANDLERS ==============

    async def populate_active_timers(data=None):
        """
        Populate the active timers container.

        Called when 'active_timers_loaded' event is emitted.
        Can be called from any thread via event bus.
        """
        containers.active_timers_container.clear()

        if not data:
            with containers.active_timers_container:
                ui.label("No active timers").classes("text-grey")
            return

        with containers.active_timers_container:
            for timer in data:
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        with ui.column():
                            ui.label(
                                f"{timer['customer_name']} - {timer['project_name']}"
                            ).classes("font-bold")
                            ui.label(f"Started: {timer['start_time']}").classes(
                                "text-sm text-grey"
                            )
                        ui.button(
                            "Stop",
                            icon="stop",
                            on_click=lambda t=timer: stop_timer(t["id"]),
                        ).props("color=negative")

    async def populate_customer_select(data=None):
        """
        Populate customer dropdown.

        Called when 'customers_loaded' event is emitted.
        """
        if data:
            options = {c["customer_id"]: c["name"] for c in data}
            containers.customer_select.options = options

            # Update projects when customer changes
            containers.customer_select.on_value_change(
                lambda e: load_projects(e.value) if e.value else None
            )

    async def populate_project_select(data=None):
        """
        Populate project dropdown.

        Called when 'projects_loaded' event is emitted.
        """
        if data:
            options = {p["project_id"]: p["name"] for p in data}
            containers.project_select.options = options

    def refresh_devops():
        """Trigger DevOps refresh (runs in background)."""
        from ..services import DevOpsService

        devops_service = DevOpsService(core)
        devops_service.refresh_incremental_async()

    def start_timer_clicked():
        """Handle start timer button click."""
        customer_id = containers.customer_select.value
        project_id = containers.project_select.value

        if not customer_id or not project_id:
            core.event_bus.notify(
                "Please select both customer and project", type_="warning"
            )
            return

        # Start timer in background
        async def start():
            await timer_service.start_timer(customer_id, project_id)
            # Reload active timers
            load_active_timers()

        import asyncio

        asyncio.create_task(start())

    async def stop_timer(timer_id: int):
        """Stop a timer."""
        # Implementation here
        core.event_bus.notify("Timer stopped!", type_="positive")
        load_active_timers()

    # ============== EVENT REGISTRATION ==============

    # Register event handlers
    core.event_bus.register("active_timers_loaded", populate_active_timers)
    core.event_bus.register("customers_loaded", populate_customer_select)
    core.event_bus.register("projects_loaded", populate_project_select)

    # Register for refresh events (when data changes)
    core.event_bus.register("timer_started", lambda: load_active_timers())
    core.event_bus.register("devops_refreshed", lambda: load_customers())

    # ============== DATA LOADING FUNCTIONS ==============

    def load_active_timers():
        """Load active timers in background."""

        async def load():
            data = await timer_service.get_active_timers()
            core.event_bus.emit("active_timers_loaded", data=data)

        # Run in background thread
        timer_service.run_in_thread(load)

    def load_customers():
        """Load customers in background."""

        async def load():
            data = await db_service.get_customers()
            core.event_bus.emit("customers_loaded", data=data)

        db_service.run_in_thread(load)

    def load_projects(customer_id: Optional[int] = None):
        """Load projects in background."""

        async def load():
            data = await db_service.get_projects(customer_id)
            core.event_bus.emit("projects_loaded", data=data)

        db_service.run_in_thread(load)

    # ============== INITIAL POPULATION ==============

    # Trigger initial data loads
    # These run in background and notify via events when done
    load_active_timers()
    load_customers()

    # Note: Projects will load when customer is selected


# ============== ALTERNATIVE: FUNCTION-BASED PATTERN ==============


def create_time_tracking_skeleton():
    """
    Alternative: Create just the skeleton without any data.

    This approach separates structure from content even more clearly.
    """
    containers = {}

    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Active Timers").classes("text-xl")
        with ui.column().classes("w-full gap-2") as active_timers:
            containers["active_timers"] = active_timers

        ui.separator()

        ui.label("Start New Timer").classes("text-xl")
        with ui.card().classes("w-full"):
            with ui.row().classes("w-full gap-4"):
                containers["customer_select"] = ui.select(
                    label="Customer",
                    options={},
                ).classes("flex-grow")

                containers["project_select"] = ui.select(
                    label="Project",
                    options={},
                ).classes("flex-grow")

                containers["start_button"] = ui.button(
                    "Start Timer",
                    icon="play_arrow",
                ).props("color=positive")

    return containers


async def populate_time_tracking_page(core: AppCore, containers: dict):
    """
    Alternative: Populate an already-created skeleton.

    This shows complete separation of structure and content.
    """
    # Create services
    db_service = DatabaseService(core)
    timer_service = TimerService(core)

    # Set up event handlers
    # ... (similar to above)

    # Trigger data loads
    # ... (similar to above)
