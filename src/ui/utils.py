"""
Utility UI Modules

Contains simple utility UI components:
- Log viewer
- Info/README viewer
"""

from nicegui import ui

from ..globals import GlobalRegistry, Logger
from .. import helpers

# ============================================================================
# Constants
# ============================================================================

# Log viewer dimensions
LOG_CARD_HEIGHT = "76vh"
LOG_CARD_MAX_WIDTH = "98vw"

# Info viewer splitter ratio (sidebar width percentage)
INFO_SPLITTER_RATIO = 20

# ============================================================================
# UI Components
# ============================================================================


def ui_log():
    """Application log viewer."""
    LOG = GlobalRegistry.get("LOG")

    if not LOG:
        with ui.card().classes("w-full p-4"):
            ui.label("Log engine not available").classes("text-negative")
        return

    with ui.card().classes(
        f"w-full max-w-[{LOG_CARD_MAX_WIDTH}] mx-auto my-8 p-2 h-[{LOG_CARD_HEIGHT}]"
    ):
        ui.label("Application Log").classes("text-h5 mb-4")
        log_textarea = ui.html(content="").classes(
            "w-full h-full overflow-auto bg-black text-white p-2 rounded"
        )
        Logger.set_log_textarea(log_textarea)
        LOG.update_log_textarea()


def ui_info():
    """Info and README viewer with markdown rendering."""
    with ui.splitter(value=INFO_SPLITTER_RATIO).classes("w-full h-full") as splitter:
        with splitter.before:
            with ui.tabs().props("vertical").classes("w-full") as info_tabs:
                ui.tab("README", icon="description")
                ui.tab("Info", icon="info")
        with splitter.after:
            with ui.tab_panels(info_tabs, value="README").classes("w-full h-full"):
                with ui.tab_panel("README"):
                    helpers.render_markdown_card("README.md")
                with ui.tab_panel("Info"):
                    helpers.render_markdown_card("INFO.md")
