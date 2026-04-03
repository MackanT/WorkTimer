from nicegui import ui, app
from . import (
    time_tracking_page,
    log_page,
    query_editor_page,
    add_data_page,
    tasks_page,
    notepad_page,
    info_page,
    settings_page,
)
from ..core.app import AppCore


async def _setup_spa_shell():
    """Set up the SPA shell with navigation and sub-pages."""
    core = await AppCore.get_or_initialize()
    core.nav_bar.render()

    # Register timer indicator — once per client
    if not app.storage.client.get("timer_indicator_registered", False):
        app.storage.client["timer_indicator_registered"] = True

        async def _on_timer_count_changed(count: int = 0, **_):
            core.nav_bar.set_timer_active(count > 0)

        core.event_bus.register("active_timer_count_changed", _on_timer_count_changed)

        # Set initial nav-bar state from DB
        try:
            result = await core.query_engine.query_db(
                "SELECT COUNT(*) as count FROM time WHERE end_time IS NULL"
            )
            active_count = int(result.iloc[0]["count"]) if not result.empty else 0
            core.nav_bar.set_timer_active(active_count > 0)
        except Exception:
            pass

    ui.sub_pages(
        {
            "/time": time_tracking_page,
            "/add_data": add_data_page,
            "/query_editor": query_editor_page,
            "/tasks": tasks_page,
            "/notepad": notepad_page,
            "/log": log_page,
            "/info": info_page,
            "/settings": settings_page,
        }
    ).classes("w-full h-full gap-0").style("overflow: hidden;")


@ui.page("/")
async def root_page():
    """Root page - redirects to /time by default."""
    await _setup_spa_shell()
    # Only navigate if actually at root
    ui.navigate.to("/time")


# ============================================================================
# Direct Access Pages (for refresh support)
# These allow refreshing on /time, /add_data, etc. without 404 errors
# Each renders the SPA shell which includes the sub-page for that route
# ============================================================================


@ui.page("/time")
async def time_page():
    """Time tracking page (supports direct access and SPA navigation)."""
    await _setup_spa_shell()


@ui.page("/add_data")
async def add_data_page_route():
    """Add data page (supports direct access and SPA navigation)."""
    await _setup_spa_shell()


@ui.page("/query_editor")
async def query_editor_page_route():
    """Query editor page (supports direct access and SPA navigation)."""
    await _setup_spa_shell()


@ui.page("/tasks")
async def tasks_page_route():
    """Tasks page (supports direct access and SPA navigation)."""
    await _setup_spa_shell()


@ui.page("/log")
async def log_page_route():
    """Log page (supports direct access and SPA navigation)."""
    await _setup_spa_shell()


@ui.page("/info")
async def info_page_route():
    """Info page (supports direct access and SPA navigation)."""
    await _setup_spa_shell()


@ui.page("/settings")
async def settings_page_route():
    """Settings page (supports direct access and SPA navigation)."""
    await _setup_spa_shell()


@ui.page("/notepad")
async def notepad_page_route():
    """Notepad page (supports direct access and SPA navigation)."""
    await _setup_spa_shell()
