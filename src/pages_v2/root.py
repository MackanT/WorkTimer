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

    # Inject global styles once — persists for entire SPA session since <head> is
    # not cleared between sub-page navigations.
    ui.add_head_html("""
        <style>
            /* Softer outlined input borders — lives in root so it persists
               across all SPA navigation without re-injection.
               Use full 'border' shorthand to override Quasar's per-side rules. */
            .q-field--outlined .q-field__control:before {
                border: 1px solid rgba(255,255,255,0.22) !important;
            }
            .q-field--outlined.q-field--focused .q-field__control:before {
                border-color: rgba(100,181,246,0.65) !important;
            }
        </style>
    """)

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
