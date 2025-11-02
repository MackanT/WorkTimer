"""
Application Layout Module

Handles the main application UI structure:
- Tab navigation setup
- UI refresh callbacks
- Tab change handlers
- Application startup tasks
"""

import asyncio
from nicegui import ui, app

from ..globals import GlobalRegistry
from .time_tracking import ui_time_tracking
from .add_data import ui_add_data
from .tasks import ui_tasks
from .query_editor import ui_query_editor
from .utils import ui_log, ui_info


def setup_ui():
    """Set up the main application UI with tabs and panels."""
    # Get global instances
    LOG = GlobalRegistry.get("LOG")
    UI = GlobalRegistry.get("UI")
    DO = GlobalRegistry.get("DO")
    
    # Enable dark mode
    dark = ui.dark_mode()
    dark.enable()

    # Create main tabs
    with ui.tabs().classes("w-full") as tabs:
        tab_time = ui.tab("Time Tracking", icon="schedule")
        tab_data_input = ui.tab("Data Input", icon="input")
        tasks_input = ui.tab("To-Do", icon="check_box")
        tab_query_editors = ui.tab("Query Editors", icon="code")
        tab_log = ui.tab("Log", icon="terminal")
        tab_info = ui.tab("Info", icon="info")

    # Set up UI refresh callbacks
    async def ui_refresh_wrapper():
        """Wrapper to use update_ui for periodic refreshes."""
        try:
            update_ui_func = GlobalRegistry.get("time_tracking_update_ui")
            if update_ui_func:
                await update_ui_func()
        except Exception as e:
            LOG.log_msg("ERROR", f"Error refreshing UI: {e}")

    def update_tab_indicator(has_active_timers):
        """Update the Time Tracking tab icon based on active timers."""
        try:
            if has_active_timers:
                tab_time.props("icon=play_circle color=positive")
            else:
                tab_time.props("icon=schedule")
        except Exception as e:
            LOG.log_msg("ERROR", f"Error updating tab indicator: {e}")

    async def update_tab_indicator_now():
        """Immediately check active timers and update the tab indicator."""
        try:
            active_count = await UI._check_active_timers()
            update_tab_indicator(active_count > 0)
        except Exception as e:
            LOG.log_msg("ERROR", f"Error updating tab indicator immediately: {e}")

    # Register for use in other modules
    GlobalRegistry.set("update_tab_indicator_now", update_tab_indicator_now)

    # Configure UI refresh engine
    UI.set_ui_refresh_callback(ui_refresh_wrapper)
    UI.set_tab_indicator_callback(update_tab_indicator)

    # Start both UI refresh and DevOps scheduled tasks after the app starts
    async def startup_tasks():
        """Start background tasks after the app has started."""
        LOG.log_msg("INFO", "Starting UI refresh task after app startup")
        await UI.start_ui_refresh()

        # Start DevOps scheduled tasks after NiceGUI is fully initialized
        await DO.initialize_scheduled_tasks()

    app.on_startup(startup_tasks)

    # Handle tab changes
    def on_tab_change(e):
        tab_value = (
            e.args["value"]
            if isinstance(e.args, dict) and "value" in e.args
            else e.args
        )
        if tab_value == tab_time.label:
            render_ui_func = GlobalRegistry.get("time_tracking_render_ui")
            if render_ui_func:
                asyncio.create_task(render_ui_func())

    tabs.on("update:model-value", on_tab_change)

    # Create tab panels with UI content
    with ui.tab_panels(tabs, value=tab_time).classes("w-full"):
        with ui.tab_panel(tab_time):
            ui_time_tracking()
        with ui.tab_panel(tab_data_input):
            ui_add_data()
        with ui.tab_panel(tab_query_editors):
            ui_query_editor()
        with ui.tab_panel(tasks_input):
            ui_tasks()
        with ui.tab_panel(tab_log):
            ui_log()
        with ui.tab_panel(tab_info):
            ui_info()
