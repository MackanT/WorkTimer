"""
Utility UI Modules

Contains simple utility UI components:
- Log viewer
- Info/README viewer
"""

import logging
from nicegui import ui

from ..globals import GlobalRegistry, LogElementHandler, LOG_FORMAT, LOG_DATE_FORMAT
from .. import helpers
from ..helpers import UI_STYLES

# ============================================================================
# Constants
# ============================================================================

# Log viewer dimensions
LOG_CARD_HEIGHT = "76vh"
LOG_CARD_MAX_WIDTH = "98vw"

# Info viewer splitter ratio (sidebar width percentage)
INFO_SPLITTER_RATIO = 20

# ============================================================================
# Helper Functions
# ============================================================================


def _attach_log_handlers(log_element):
    """Attach all application loggers to the UI log element.
    
    Follows NiceGUI's recommended pattern: get each logger by name,
    create a handler, attach it, and register cleanup on disconnect.
    
    Args:
        log_element: NiceGUI ui.log element to receive messages
    """
    # Get all loggers that were created during initialization
    logger_names = ["WorkTimer", "Database", "DevOps"]
    handlers = []
    
    for name in logger_names:
        logger = logging.getLogger(name)
        # Create handler with formatter
        handler = LogElementHandler(log_element)
        formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
        handler.setFormatter(formatter)
        # Attach to logger
        logger.addHandler(handler)
        handlers.append((logger, handler))
    
    # Clean up handlers when client disconnects (prevents memory leaks)
    def cleanup():
        for logger, handler in handlers:
            try:
                logger.removeHandler(handler)
            except Exception:
                pass
    
    ui.context.client.on_disconnect(cleanup)


# ============================================================================
# UI Components
# ============================================================================


def ui_log():
    """Application log viewer with modern styled log display."""
    LOG = GlobalRegistry.get("LOG")

    if not LOG:
        with ui.card().classes(UI_STYLES.get_layout_classes("full_width_padded")):
            ui.label("Log engine not available").classes(
                UI_STYLES.get_layout_classes("text_negative")
            )
        return

    with ui.card().classes(f"w-full max-w-[{LOG_CARD_MAX_WIDTH}] mx-auto my-4 p-6"):
        # Header with icon and title
        with ui.row().classes("w-full items-center gap-3 mb-4"):
            ui.icon("terminal", size="md").classes("text-blue-400")
            ui.label("Application Log").classes("text-h5 text-white font-medium")

        # Log display container
        with ui.element().classes("w-full"):
            log_widget = ui.log(max_lines=None).classes(
                "w-full bg-[#282a36] text-white p-4 rounded-lg overflow-auto"
            )
            try:
                log_widget.style(f"height: {LOG_CARD_HEIGHT};")
            except Exception:
                pass

            # Attach all loggers to this UI element (NiceGUI pattern)
            _attach_log_handlers(log_widget)


def ui_info():
    """Info and README viewer with markdown rendering."""
    with ui.splitter(value=INFO_SPLITTER_RATIO).classes(
        UI_STYLES.get_layout_classes("full_size")
    ) as splitter:
        with splitter.before:
            with (
                ui.tabs()
                .props("vertical")
                .classes(UI_STYLES.get_layout_classes("full_width")) as info_tabs
            ):
                ui.tab("README", icon="description")
                ui.tab("Info", icon="info")
                ui.tab("Devops Contacts", icon="merge")
        with splitter.after:
            with ui.tab_panels(info_tabs, value="README").classes(
                UI_STYLES.get_layout_classes("full_size")
            ):
                with ui.tab_panel("README"):
                    helpers.render_markdown_card("README.md")
                with ui.tab_panel("Info"):
                    helpers.render_markdown_card("INFO.md")
                with ui.tab_panel("Devops Contacts"):
                    helpers.render_markdown_card("DEVOPS_CONTACTS.md")
