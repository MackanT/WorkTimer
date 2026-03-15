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
    """Root page that hosts sub-pages for a SPA-like navigation."""

    core = await AppCore.get_or_initialize()
    core.nav_bar.render()

    # Define sub-pages mapping - paths are relative to root
    ui.sub_pages(
        {
            "/": time_tracking_page,
            "/add_data": add_data_page,
            "/query_editor": query_editor_page,
            "/tasks": tasks_page,
            "/log": log_page,
            "/info": info_page,
        }
    ).classes("w-full h-full px-6 py-3 gap-0")
