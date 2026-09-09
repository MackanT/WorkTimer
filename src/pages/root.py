import asyncio

from nicegui import ui, app
from . import (
    time_tracking_page,
    log_page,
    query_editor_page,
    add_data_page,
    board_page,
    reports_page,
    tasks_page,
    notepad_page,
    info_page,
    settings_page,
)
from ..core.app import AppCore
from ..ui.command_palette import setup_command_palette


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
    setup_command_palette(core)  # global Ctrl+K — one dialog + binding per client

    # Register timer indicator — once per client
    if not app.storage.client.get("timer_indicator_registered", False):
        app.storage.client["timer_indicator_registered"] = True

        async def _on_timer_count_changed(count: int = 0, names: list = None, **_):
            core.nav_bar.set_active_timers(names or [])

        core.event_bus.register("active_timer_count_changed", _on_timer_count_changed)

        # ── What's-new dialog (shared by the update badge + post-update popup) ──
        # Built inside a shell-level host: callers run as background tasks with
        # no slot context, so the target slot must be entered explicitly.
        _whats_new_host = ui.element("div").classes("hidden")

        def _show_whats_new(md_text: str, title: str):
            with _whats_new_host, ui.dialog() as dlg, ui.card().classes(
                "rounded-lg"
            ).style(
                "min-width: 480px; max-width: min(720px, 92vw);"
            ):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.icon("new_releases", size="sm").classes("text-amber-400")
                    ui.label(title).classes("text-base font-semibold flex-1")
                    ui.button(icon="close", on_click=dlg.close).props(
                        "flat dense round color=grey-6"
                    )
                with ui.scroll_area().classes("w-full").style("max-height: 60vh;"):
                    ui.markdown(md_text)
            dlg.on("hide", lambda: dlg.delete())  # shell-lived — don't accumulate
            dlg.open()

        # Background update check — fires once per process per 24 h. The badge
        # is clickable: it fetches main's changelog (the local one predates the
        # announced version) and shows the sections newer than this install.
        async def _check_for_update():
            from ..services.update_checker import (
                check_for_update,
                extract_whats_new,
                fetch_remote_changelog_blocking,
            )
            try:
                result = await check_for_update()
                if result["available"]:

                    async def _show_remote_whats_new():
                        try:
                            loop = asyncio.get_event_loop()
                            text = await loop.run_in_executor(
                                None, fetch_remote_changelog_blocking
                            )
                            news = extract_whats_new(text, result["current"])
                        except Exception:
                            news = ""
                        _show_whats_new(
                            news or "_Could not load the changelog._",
                            f"What's new in v{result['latest']}",
                        )

                    core.nav_bar.set_update_available(
                        result["latest"], on_click=_show_remote_whats_new
                    )
            except Exception:
                pass

        asyncio.create_task(_check_for_update())

        # Post-update popup — once per install after a version change: show the
        # local changelog sections between the last-seen version and this one.
        async def _maybe_show_post_update_news():
            from pathlib import Path

            from ..services.update_checker import _current_version, extract_whats_new

            try:
                current = _current_version()
                last_seen = app.storage.general.get("last_seen_version")
                app.storage.general["last_seen_version"] = current
                if not last_seen or last_seen == current or current == "unknown":
                    return  # first run ever, or no change — no popup
                changelog = (
                    Path(__file__).parent.parent.parent / "docs" / "CHANGELOG.md"
                ).read_text(encoding="utf-8")
                news = extract_whats_new(changelog, last_seen)
                if news:
                    _show_whats_new(news, f"WorkTimer updated to v{current}")
            except Exception:
                pass

        asyncio.create_task(_maybe_show_post_update_news())

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
            "/reports": reports_page,
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
# These allow refreshing on /time, /add_data, etc. without 404 errors.
# Every route renders the same SPA shell, which routes to the matching sub-page
# — registered in a loop instead of nine identical handler functions.
# ============================================================================

_SPA_ROUTES = [
    "/time",
    "/add_data",
    "/board",
    "/reports",
    "/query_editor",
    "/tasks",
    "/notepad",
    "/log",
    "/info",
    "/settings",
]


def _register_spa_route(path: str) -> None:
    async def spa_route():
        await _setup_spa_shell()

    spa_route.__name__ = f"spa_route_{path.strip('/')}"
    ui.page(path)(spa_route)


for _path in _SPA_ROUTES:
    _register_spa_route(_path)
