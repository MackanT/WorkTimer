"""
Application Core - Per-Client Instance Management

Each client gets their own AppCore instance with isolated state.
This enables true multi-client support with no shared state pollution.
"""

from collections import deque
import logging
from typing import Optional, Dict
from nicegui import app
from ..config import ConfigLoader
from ..database import Database
from ..devops import DevOpsManager
from ..ui.elements import NavigationBar
from .events import PageEventBus
import asyncio
from nicegui import ui

# Module-level storage for AppCore instances (per-client, by client ID)
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

        self._background_tasks = {}
        self.theme = config_loader.get_raw_dict("theme")
        self._init_lock = asyncio.Lock()

        self.nav_bar = NavigationBar(theme=self.theme)

        # Initialize event bus
        self.event_bus = PageEventBus()

        self.log_buffer = deque(maxlen=500)

        def global_log_handler(
            message: str, level: str = "INFO", timestamp: str = "", logger: str = "App"
        ):
            log_entry = {
                "message": message,
                "level": level,
                "timestamp": timestamp,
                "logger": logger,
                "formatted": f"{timestamp} | {level:<8} | {logger:<9} :: {message}",
            }
            self.log_buffer.append(log_entry)

        self.event_bus.register("log_message", global_log_handler)

        # Initialize logging
        self.logger = self._setup_logger("AppCore")
        self.logger.info("Initializing new AppCore instance")

        # Initialize engines (these are per-client now!)
        self.query_engine = None
        self.devops_engine = None
        self.add_data_engine = None
        self._initialized = False

        self.logger.info("AppCore initialized")

    def _attach_root_logger_handler(self):
        """Attach EventBus handler to root logger for global log capture."""
        try:
            from .events import EventBusLogHandler

            root_logger = logging.getLogger()

            # Remove any existing EventBusLogHandlers first
            for handler in root_logger.handlers[:]:
                if isinstance(handler, EventBusLogHandler):
                    root_logger.removeHandler(handler)

            # Add EventBus handler for UI
            root_handler = EventBusLogHandler(self.event_bus)
            root_handler.setLevel(logging.DEBUG if self.debug else logging.INFO)
            root_logger.addHandler(root_handler)

            # Add StreamHandler for terminal output
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG if self.debug else logging.INFO)
            # Format for terminal
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)-12s :: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

            root_logger.setLevel(logging.DEBUG if self.debug else logging.INFO)

            self.logger.debug("Root logger attached to EventBus and console")
            print(f"[AppCore] Logging initialized - Debug mode: {self.debug}")
        except Exception as e:
            # Non-fatal - log to stderr as fallback
            print(f"Warning: Failed to attach root logger: {e}")
            import traceback

            traceback.print_exc()

    def _setup_logger(self, name: str) -> logging.Logger:
        """Set up a logger with appropriate level and EventBus handler."""
        logger = logging.getLogger(name)

        from .events import EventBusLogHandler

        # Check if EventBus handler already exists
        has_eventbus_handler = any(
            isinstance(h, EventBusLogHandler) for h in logger.handlers
        )

        if not has_eventbus_handler:
            # Set logger level
            logger.setLevel(logging.DEBUG if self.debug else logging.INFO)

            # Add EventBus handler
            if hasattr(self, "event_bus") and self.event_bus:
                handler = EventBusLogHandler(self.event_bus)
                handler.setLevel(logging.DEBUG if self.debug else logging.INFO)
                logger.addHandler(handler)
                # Don't propagate to avoid duplicate messages
                logger.propagate = False

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

        self._attach_root_logger_handler()
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
            # Cancel all background tasks for this core
            for page_name, tasks in list(core._background_tasks.items()):
                for task in tasks:
                    if not task.done() and not task.cancelled():
                        core.logger.debug(f"Cleanup: Cancelling {page_name} task")
                        task.cancel()
            core._background_tasks.clear()

            # Remove core instance
            if client_id in _app_cores:
                del _app_cores[client_id]
                core.logger.debug(f"Client {client_id} disconnected, core cleaned up")

        context.client.on_disconnect(cleanup)

        return core

    @classmethod
    async def get_or_initialize(
        cls, config_loader: Optional[ConfigLoader] = None
    ) -> "AppCore":
        """
        Get or create AppCore, initialize engines if needed, and apply theme.
        One-stop shop for page setup.
        """
        core = cls.get_or_create(config_loader=config_loader or get_config_loader())

        async with core._init_lock:
            if not core._initialized:
                await core.initialize_engines()
        core.apply_theme()

        if not app.storage.client.get("navigation_created", False):
            core.nav_bar.render()

        return core

    def _setup_page_timers(self, page_name: str, *task_fns):
        """
        Cancel existing timers for a page and start new ones.

        Args:
            page_name: Unique identifier for the page (e.g. "time_tracking")
            *task_fns: Async functions to run as background tasks
        """

        for timer in self._background_tasks.get(page_name, []):
            timer.cancel()

        # Start new client-bound tasks using asyncio.create_task
        # These will be tracked and auto-cancelled on disconnect via cleanup()
        self._background_tasks[page_name] = [
            asyncio.create_task(fn()) for fn in task_fns
        ]
        self.logger.debug(
            f"Started {len(task_fns)} background task(s) for page '{page_name}'"
        )

        ## Debug: Print all current tasks with "value_refresh_timer" in their name
        # current_tasks = asyncio.all_tasks()
        # same_name = [
        #     t
        #     for t in current_tasks
        #     if t.get_name() and "value_refresh_timer" in str(t.get_coro().__qualname__)
        # ]
        # print(f"Value refresh timer started - {len(same_name)} instance(s) running")

    def apply_theme(self):
        """Apply Quasar color theme for current page context."""

        dark = ui.dark_mode()
        dark.enable()

        ui.colors(
            primary=self.theme.get("primary"),
            secondary=self.theme.get("secondary"),
            dark=self.theme.get("dark"),
            dark_page=self.theme.get("dark_page"),
            positive=self.theme.get("positive"),
            negative=self.theme.get("negative"),
            info=self.theme.get("info"),
            warning=self.theme.get("warning"),
        )


# Singleton config loader (configs are immutable, so sharing is safe)
_config_loader: Optional[ConfigLoader] = None


def get_config_loader() -> ConfigLoader:
    """
    Get the shared config loader instance.

    Configs are immutable, so sharing across clients is safe and efficient.
    Loads configs once on first call and caches them.
    """
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
        _config_loader.load_all()
    return _config_loader
