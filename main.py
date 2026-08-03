"""
WorkTimer V5

This is the main file doing the following work:
1. Minimal startup code
2. Per-client state isolation using @ui.page decorators
3. Thread-safe operations with event-driven UI updates
4. Clear separation: skeleton → populate → notify pattern
"""

import os
import secrets
from pathlib import Path

from nicegui import ui
from dotenv import load_dotenv

# Import only what we need for startup
from src.core import get_config_loader
from src.pages import root_page  # noqa: F401 — importing registers all @ui.page routes


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


def _get_storage_secret() -> str:
    """Return a per-installation random storage secret, generated on first run.

    Replaces the old hardcoded secret. Persisted in data/ so app.storage.user
    survives restarts.
    """
    secret_file = Path("data") / ".storage_secret"
    if secret_file.exists():
        stored = secret_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    secret = secrets.token_hex(32)
    secret_file.parent.mkdir(exist_ok=True)
    secret_file.write_text(secret, encoding="utf-8")
    return secret


# NOTE on layout: the SPA layout CSS (position:fixed on .nicegui-sub-pages etc.)
# is injected per-client in root.py's _setup_spa_shell(), because
# ui.add_head_html() must run inside a @ui.page context to reach served pages.


def main():
    """Main entry point."""

    # Initialize app
    initialize_app()

    # Start the server
    # Each route defined with @ui.page() is automatically registered.
    # Binds to localhost by default — the app has no authentication and the DB
    # holds PAT tokens. Set HOST=0.0.0.0 in .env to expose it on the LAN.
    ui.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8080")),
        title="WorkTimer",
        favicon="icons/worktimer.ico",
        reload=False,  # Set to True for development hot-reload
        show=False,
        reconnect_timeout=10,
        storage_secret=_get_storage_secret(),  # Required for app.storage.user
    )


if __name__ == "__main__":
    main()
