from nicegui import ui, app
from . import (
    time_tracking_page,
    log_page,
    query_editor_page,
    add_data_page,
    board_page,
    tasks_page,
    notepad_page,
    info_page,
    settings_page,
)
from ..core.app import AppCore


# Layout CSS injected per-client (ui.add_head_html must run inside a page context).
_LAYOUT_CSS = """
<style>
:root { --wt-nav-h: 68px; --wt-toolbar-h: 56px; }
html, body { overflow: hidden !important; }

/* height:auto lets top+bottom fully determine the element size.
   Without it, h-full (height:100%) overconstrained the fixed element,
   causing CSS to recompute bottom and ignore bottom:12px. */
.nicegui-sub-pages {
    position: fixed !important;
    top: var(--wt-nav-h) !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 12px !important;
    height: auto !important;
    display: flex !important;
    flex-direction: column !important;
    overflow: hidden !important;
    z-index: 0 !important;
    /* NiceGUI's nicegui.css adds gap:1rem and padding:1rem to this element.
       Override both so spacing comes entirely from child margins. */
    gap: 0 !important;
    padding: 0 !important;
}
.wt-page-content {
    flex: 1 !important;
    min-height: 0 !important;
}

/* Toolbar: outer spacing so rounded-md corners are visible from edges.
   Override w-full to account for 8px side margins. */
.wt-toolbar {
    margin: 8px 8px 0 !important;
    width: calc(100% - 16px) !important;
}

/* Tab-panels container (add_data, info): match page_card spacing (mx-4 my-2 = 8px 16px). */
.wt-page-content.q-tab-panels {
    margin: 8px 16px 8px !important;
    width: calc(100% - 32px) !important;
}

/* Scroll-area container (time_tracking): match page_card's mx-4 my-2 (8px top/bottom, 16px sides). */
.nicegui-scroll-area.wt-page-content {
    margin: 8px 16px 8px !important;
    width: calc(100% - 32px) !important;
}

/* Scroll-area: NiceGUI's nicegui.css adds padding:1rem to q-scrollarea__content.
   Zero it so card tops align at the scroll area edge, then rely on margin-top
   on the scroll area itself for the gap below the toolbar. */
.nicegui-scroll-area.wt-page-content .q-scrollarea__content {
    height: 100% !important;
    min-height: 0 !important;
    padding: 0 !important;
}
.nicegui-scroll-area.wt-page-content .q-scrollarea__content > .nicegui-row {
    height: 100% !important;
    min-height: 0 !important;
}

/* Hide scrollbar on horizontally-scrollable rows while keeping scroll functionality */
.wt-nav-scroll::-webkit-scrollbar,
.wt-toolbar-scroll::-webkit-scrollbar { display: none; }

/* Tab-panels: propagate definite height all the way down the chain.
   nicegui-tab-panel is the class NiceGUI puts on the q-tab-panel element.
   Use descendant selector (not >) in case Quasar wraps with a transition div. */
.wt-page-content.q-tab-panels .nicegui-tab-panel {
    height: 100% !important;
    min-height: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
}
/* First child inside the tab panel (nicegui-row or nicegui-column) */
.wt-page-content.q-tab-panels .nicegui-tab-panel > .nicegui-row,
.wt-page-content.q-tab-panels .nicegui-tab-panel > .nicegui-column {
    height: 100% !important;
    min-height: 0 !important;
}
</style>
<script>
requestAnimationFrame(function () {
    var pc = document.querySelector('.q-page-container');
    if (pc) {
        var h = parseFloat(getComputedStyle(pc).paddingTop);
        if (h > 0) {
            document.documentElement.style.setProperty('--wt-nav-h', h + 'px');
        }
    }
});
document.addEventListener('keydown', function (e) {
    if (e.key === 'F5') e.preventDefault();
});
</script>
"""


async def _setup_spa_shell():
    """Set up the SPA shell with navigation and sub-pages."""
    ui.add_head_html(_LAYOUT_CSS)
    core = await AppCore.get_or_initialize()
    core.nav_bar.render()

    # Register timer indicator — once per client
    if not app.storage.client.get("timer_indicator_registered", False):
        app.storage.client["timer_indicator_registered"] = True

        async def _on_timer_count_changed(count: int = 0, names: list = None, **_):
            core.nav_bar.set_active_timers(names or [])

        core.event_bus.register("active_timer_count_changed", _on_timer_count_changed)

        # Set initial nav-bar state from DB
        try:
            result = await core.query_engine.query_db(
                """
                SELECT c.customer_name, p.project_name
                FROM time t
                JOIN customers c ON t.customer_id = c.customer_id
                JOIN projects p ON t.project_id = p.project_id
                WHERE t.end_time IS NULL
                ORDER BY c.customer_name, p.project_name
                """
            )
            initial_names = [
                f"{r['customer_name']} / {r['project_name']}"
                for _, r in result.iterrows()
            ] if not result.empty else []
            core.nav_bar.set_active_timers(initial_names)
        except Exception:
            pass

    ui.sub_pages(
        {
            "/time": time_tracking_page,
            "/add_data": add_data_page,
            "/board": board_page,
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


@ui.page("/board")
async def board_page_route():
    """Board page (supports direct access and SPA navigation)."""
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
