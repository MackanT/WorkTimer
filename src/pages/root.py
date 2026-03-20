from nicegui import ui
from . import (
    time_tracking_page,
    log_page,
    query_editor_page,
    add_data_page,
    tasks_page,
    info_page,
)
from ..core.app import AppCore


@ui.page("/")
async def root_page():
    """Root page that hosts sub-pages for SPA navigation."""

    core = await AppCore.get_or_initialize()
    core.nav_bar.render()

    # Define sub-pages mapping - all pages are sub-pages for SPA behavior
    ui.sub_pages(
        {
            "/time": time_tracking_page,
            "/add_data": add_data_page,
            "/query_editor": query_editor_page,
            "/tasks": tasks_page,
            "/log": log_page,
            "/info": info_page,
        }
    ).classes("w-full h-full gap-0")

    # Auto-navigate to time tracking page on root load
    ui.navigate.to("/time")


# ============================================================================
# Direct Access Redirects (for refresh support)
# These allow refreshing on /time, /add_data, etc. without 404 errors
# They render the root page which contains the sub-pages
# ============================================================================


@ui.page("/time")
async def time_redirect():
    """Redirect to root SPA for time tracking (handles refresh on /time)."""
    await root_page()


@ui.page("/add_data")
async def add_data_redirect():
    """Redirect to root SPA for add data (handles refresh on /add_data)."""
    await root_page()
    ui.navigate.to("/add_data")


@ui.page("/query_editor")
async def query_editor_redirect():
    """Redirect to root SPA for query editor (handles refresh on /query_editor)."""
    await root_page()
    ui.navigate.to("/query_editor")


@ui.page("/tasks")
async def tasks_redirect():
    """Redirect to root SPA for tasks (handles refresh on /tasks)."""
    await root_page()
    ui.navigate.to("/tasks")


@ui.page("/log")
async def log_redirect():
    """Redirect to root SPA for log (handles refresh on /log)."""
    await root_page()
    ui.navigate.to("/log")


@ui.page("/info")
async def info_redirect():
    """Redirect to root SPA for info (handles refresh on /info)."""
    await root_page()
    ui.navigate.to("/info")
