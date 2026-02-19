"""
Keyboard event handlers for debugging and testing.
Provides reusable keyboard shortcuts that can be attached to any page.
"""

from nicegui import ui
from nicegui.events import KeyEventArguments
from ..core.app import AppCore


def setup_debug_keyboard_handlers(core: AppCore):
    """
    Setup keyboard event handlers for debugging.
    Must be called within a page context.

    Current shortcuts:
    - 'j': Log a test message (visible in Log page and terminal)

    Args:
        core: The AppCore instance for the current client
    """

    def handle_key(e: KeyEventArguments):
        if e.key == "j" and not e.action.repeat:
            if e.action.keyup:
                core.logger.info("This is a test log message triggered by 'j' key")

    ui.keyboard(on_key=handle_key)
