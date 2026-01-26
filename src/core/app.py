"""
Application Core - Per-Client Instance Management

Each client gets their own AppCore instance with isolated state.
This enables true multi-client support with no shared state pollution.
"""

import logging
from typing import Optional, Dict
from nicegui import app
from ..config import ConfigLoader
from ..database import Database
from ..devops import DevOpsManager
from .events import PageEventBus

# Module-level storage for AppCore instances (per-client, by client ID)
# This avoids JSON serialization issues with app.storage.user
_app_cores: Dict[str, "AppCore"] = {}


class AppCore:
    """
    Per-client application core.

    Contains all engines and services for a single client session.
    Stored in app.storage.user to maintain per-client isolation.

    Usage:
        @ui.page('/')
        def index():
            core = AppCore.get_or_create()
            # Use core.event_bus, core.query_engine, etc.
    """

    def __init__(self, config_loader: ConfigLoader):
        """
        Initialize a new application core instance.

        Args:
            config_loader: Shared config loader (configs are immutable)
        """
        self.config_loader = config_loader

        # Load configurations
        configs = config_loader.load_all()
        self.settings = configs["settings"]
        self.data_config = configs["data"]
        self.ui_config = config_loader.get_raw_dict("ui")
        self.tasks_config = config_loader.get_raw_dict("tasks")
        self.query_config = config_loader.get_raw_dict("query")
        self.devops_contacts = config_loader.get_raw_dict("devops_contacts")
        self.task_visuals = config_loader.get_raw_dict("task_visuals")
        self.debug = self.settings.debug_mode

        # Initialize logging
        self.logger = self._setup_logger("AppCore")
        self.logger.info("Initializing new AppCore instance")

        # Initialize event bus (will auto-capture context)
        self.event_bus = PageEventBus(logger=self._setup_logger("EventBus"))

        # Initialize engines (these are per-client now!)
        self.query_engine = None
        self.devops_engine = None
        self.add_data_engine = None

        # Lazy initialization flag
        self._initialized = False

    def _setup_logger(self, name: str) -> logging.Logger:
        """Set up a logger with appropriate level."""
        logger = logging.getLogger(name)
        if self.debug:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)
        return logger

    async def initialize_engines(self):
        """
        Initialize all engines asynchronously.

        Call this ONCE per client, typically on first page load.
        Subsequent page navigations reuse the same engines.
        """
        if self._initialized:
            self.logger.debug("Engines already initialized, skipping")
            return

        self.logger.info("Initializing engines...")

        try:
            # Initialize database/query engine
            from ..globals import QueryEngine

            db_logger = self._setup_logger("Database")
            self.query_engine = QueryEngine(
                file_name=self.settings.db_path, log_engine=db_logger
            )
            await self.query_engine.refresh()
            self.logger.info("Query engine initialized")

            # Initialize data engine
            from ..globals import AddData

            self.add_data_engine = AddData(
                query_engine=self.query_engine, log_engine=self.logger
            )
            await self.add_data_engine.refresh()
            self.logger.info("Data engine initialized")

            # Initialize DevOps engine
            from ..globals import DevOpsEngine

            do_logger = self._setup_logger("DevOps")
            self.devops_engine = DevOpsEngine(
                query_engine=self.query_engine, log_engine=do_logger
            )
            await self.devops_engine.initialize()
            self.logger.info("DevOps engine initialized")

            self._initialized = True
            self.logger.info("All engines initialized successfully")

            # Notify user
            self.event_bus.notify(
                "WorkTimer initialized successfully!", type_="positive"
            )

        except Exception as e:
            self.logger.error(f"Failed to initialize engines: {e}")
            self.event_bus.notify(f"Initialization failed: {e}", type_="negative")
            raise

    @classmethod
    def get_or_create(cls, config_loader: Optional[ConfigLoader] = None) -> "AppCore":
        """
        Get existing AppCore for this client or create a new one.

        Uses module-level storage keyed by client ID for per-client isolation.
        This avoids JSON serialization issues with app.storage.user.

        Args:
            config_loader: Required for first creation, optional for subsequent calls

        Returns:
            AppCore instance for this client
        """
        # Get client ID for this connection
        from nicegui import context

        client_id = context.client.id

        # Check if we already have an instance for this client
        if client_id in _app_cores:
            return _app_cores[client_id]

        # Create new instance
        if config_loader is None:
            # For subsequent calls, we can create a new loader
            # (configs are loaded from disk, so this is safe)
            config_loader = ConfigLoader()

        core = cls(config_loader=config_loader)
        _app_cores[client_id] = core

        # Clean up when client disconnects
        def cleanup():
            if client_id in _app_cores:
                del _app_cores[client_id]

        context.client.on_disconnect(cleanup)

        return core

    def get_active_customer_id(self) -> Optional[int]:
        """Get the currently selected customer ID for this client."""
        return app.storage.user.get("active_customer_id")

    def set_active_customer_id(self, customer_id: int):
        """Set the currently selected customer ID for this client."""
        app.storage.user["active_customer_id"] = customer_id
        self.logger.debug(f"Set active customer to {customer_id}")

    def get_active_project_id(self) -> Optional[int]:
        """Get the currently selected project ID for this client."""
        return app.storage.user.get("active_project_id")

    def set_active_project_id(self, project_id: int):
        """Set the currently selected project ID for this client."""
        app.storage.user["active_project_id"] = project_id
        self.logger.debug(f"Set active project to {project_id}")


# Singleton config loader (configs are immutable, so sharing is safe)
_config_loader: Optional[ConfigLoader] = None


def get_config_loader() -> ConfigLoader:
    """
    Get the shared config loader instance.

    Configs are immutable, so sharing across clients is safe and efficient.
    """
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader
