"""
Utility UI Modules

Contains simple utility UI components:
- Log viewer
- Info/README viewer
"""

from nicegui import ui

from ..globals import GlobalRegistry, Logger
from .. import helpers


def ui_log():
    """Application log viewer."""
    LOG = GlobalRegistry.get("LOG")
    
    with ui.card().classes("w-full max-w-[98vw] mx-auto my-8 p-2 h-[76vh]"):
        ui.label("Application Log").classes("text-h5 mb-4")
        log_textarea = ui.html(content="").classes(
            "w-full h-full overflow-auto bg-black text-white p-2 rounded"
        )
        Logger.set_log_textarea(log_textarea)
        LOG.update_log_textarea()


def ui_info():
    """Info and README viewer with markdown rendering."""
    with ui.splitter(value=20).classes("w-full h-full") as splitter:
        with splitter.before:
            with ui.tabs().props("vertical").classes("w-full") as info_tabs:
                tab_readme = ui.tab("README", icon="description")
                tab_info = ui.tab("Info", icon="info")
        with splitter.after:
            with ui.tab_panels(info_tabs, value=tab_readme).classes("w-full h-full"):
                with ui.tab_panel(tab_readme):
                    helpers.render_markdown_card("README.md")
                with ui.tab_panel(tab_info):
                    helpers.render_markdown_card("INFO.md")
