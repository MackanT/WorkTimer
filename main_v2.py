"""
WorkTimer V2 - Refactored Main Entry Point

This is the new main file that demonstrates the clean architecture:
1. Minimal startup code
2. Per-client state isolation using @ui.page decorators
3. Thread-safe operations with event-driven UI updates
4. Clear separation: skeleton → populate → notify pattern

Run alongside the old version:
    Old: uv run main.py (or python src/main.py)
    New: python main_v2.py

The old application is completely unchanged and continues to work.
"""

from nicegui import ui
from dotenv import load_dotenv

# Import only what we need for startup
from src.core import get_config_loader
from src.pages_v2 import time_tracking_page, test_page


def initialize_app():
    """
    Initialize the application.
    
    This is minimal - just configuration loading.
    Everything else happens per-client in @ui.page functions.
    """
    # Load environment variables
    load_dotenv()
    
    # Pre-load configuration (configs are immutable, so sharing is safe)
    config_loader = get_config_loader()
    configs = config_loader.load_all()
    
    print("=" * 60)
    print("WorkTimer V2 - Refactored Architecture")
    print("=" * 60)
    print(f"Database: {configs['settings'].db_name}")
    print(f"Debug mode: {configs['settings'].debug_mode}")
    print(f"Multi-client support: Enabled (with storage_secret)")
    print(f"Thread safety: Enabled via ui.context")
    print("=" * 60)
    print("\nAccess the application at: http://localhost:8080")
    print("\nPress Ctrl+C to stop the server.")
    print("=" * 60)


def setup_global_ui():
    """
    Set up global UI configuration.
    
    This runs once for the entire application, not per-client.
    """
    # Disable F5 refresh
    ui.add_head_html("""
    <script>
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F5') {
            e.preventDefault();
        }
    });
    </script>
    """)


# ============== PAGE ROUTES ==============

# Pages are imported above and registered via their @ui.page decorators
# Each page is completely isolated per-client via app.storage.user

# Example of adding more pages:
# 
# @ui.page('/data')
# def data_input_page():
#     core = AppCore.get_or_create(config_loader=get_config_loader())
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
        title="WorkTimer V2",
        favicon="icons/worktimer.ico",
        reload=False,  # Set to True for development hot-reload
        show=False,    # Don't auto-open browser
        storage_secret="worktimer-v2-secret-change-in-production",  # Required for app.storage.user
    )


if __name__ == "__main__":
    main()
