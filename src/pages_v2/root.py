from nicegui import ui
from . import (
    time_tracking_page,
    log_page,
    query_editor_page,
    add_data_page,
    tasks_page,
    info_page,
    test_page,
)
from ..ui.navigation import create_navigation


@ui.page("/")
def root_page():
    """Root page that hosts sub-pages for a SPA-like navigation."""

    # Persistent top navigation
    create_navigation()

    # Define sub-pages mapping - paths are relative to root
    ui.sub_pages(
        {
            "/": time_tracking_page,
            "/add_data": add_data_page,
            "/query_editor": query_editor_page,
            "/tasks": tasks_page,
            "/log": log_page,
            "/info": info_page,
            "/test": test_page,
        }
    )
