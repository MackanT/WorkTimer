"""
Notepad Page

"""

from pathlib import Path
import yaml
from nicegui import core, ui
from ..core.app import AppCore
from ..ui.elements import toolbar, page_card


async def notepad_page():
    """Notepad page — simple in-memory note-taking."""
    core = await AppCore.get_or_initialize()

    def render_toolbar():
        with toolbar(core.theme):
            ui.icon("note", size="md").classes("text-amber-400")
            ui.label("Notepad - Currently WIP").classes(
                "text-h5 text-white font-medium"
            )

    def render_notepad():
        with page_card():
            ui.markdown(
                "This is a simple notepad page. You can write notes here and they will be saved in memory for the session. This is just a placeholder for now."
            )
            ui.textarea("Write your notes here...").classes("w-full h-64")

    render_toolbar()
    render_notepad()
