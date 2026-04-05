"""
WorkTimer V5

This is the main file doing the following work:
1. Minimal startup code
2. Per-client state isolation using @ui.page decorators
3. Thread-safe operations with event-driven UI updates
4. Clear separation: skeleton → populate → notify pattern
"""

from nicegui import ui
from nicegui.events import KeyEventArguments
from dotenv import load_dotenv
import logging

# Import only what we need for startup
from src.core import get_config_loader
from src.pages import root_page  # Root handles all sub-pages for SPA


def initialize_app():
    """Initialize the application."""

    # Load environment variables
    load_dotenv()

    # Pre-load configuration
    print("=== WorkTimer V5 Initialization ===")
    config_loader = get_config_loader()
    configs = config_loader.load_all()

    print("=" * 60)
    print("WorkTimer V5")
    print("=" * 60)
    print(f"Database: {configs['settings'].db_path}")
    print(f"Debug mode: {configs['settings'].debug_mode}")
    print("Multi-client support: Enabled (with storage_secret)")
    print("Thread safety: Enabled via ui.context")
    print("=" * 60)
    print("\nPress Ctrl+C to stop the server.")
    print("=" * 60)


def setup_global_ui():
    """
    Set up global UI configuration.

    This runs once for the entire application, not per-client.
    """
    # Layout strategy: position:fixed on .nicegui-sub-pages.
    #
    # Quasar only ever sets min-height (never height) on q-layout and q-page
    # via inline styles.  height:100% chains always break because percentage
    # heights require *definite* heights on every ancestor — min-height is not
    # definite.  Every previous approach using the height chain failed for this
    # reason.
    #
    # Solution: take nicegui-sub-pages out of normal flow with position:fixed,
    # pinned to top=nav-height, left/right/bottom=0.  No parent height chain
    # is required.  The fallback --wt-nav-h:68px matches our observed nav bar
    # height; rAF reads Quasar's authoritative padding-top and updates it.
    # NOTE: ui.add_head_html() must run inside a @ui.page context to be
    # injected into served pages.  Layout CSS is now injected in root.py's
    # _setup_spa_shell() instead.

    # Set up keyboard event handler for testing
    def handle_key(e: KeyEventArguments):
        if e.key == "j" and not e.action.repeat:
            if e.action.keyup:
                # Get a logger and log test message
                logger = logging.getLogger("KeyHandler")
                logger.info("This is a test log message triggered by 'j' key")
                print("[KeyHandler] Test log message sent")

    ui.keyboard(on_key=handle_key)


# ============== PAGE ROUTES ==============

# Pages are imported above and registered via their @ui.page decorators
# Each page is completely isolated per-client via app.storage.user

# Example of adding more pages:
#
# @ui.page('/data')
# async def data_input_page():
#     core = await AppCore.get_or_initialize()
#     # ... create skeleton
#     # ... register events
#     # ... trigger data loads
#
# @ui.page('/tasks')
# def tasks_page():
#     # Similar pattern
#     pass


# ============== MAIN ENTRY POINT ==============


def main():
    """Main entry point."""

    # Initialize app
    initialize_app()

    # Set up global UI configuration
    setup_global_ui()

    # Start the server
    # Each route defined with @ui.page() is automatically registered
    ui.run(
        host="0.0.0.0",
        port=8080,
        title="WorkTimer V5",
        favicon="icons/worktimer.ico",
        reload=False,  # Set to True for development hot-reload
        show=False,
        reconnect_timeout=10,
        storage_secret="worktimer-v5-secret-change-in-production",  # Required for app.storage.user
    )


if __name__ == "__main__":
    main()
