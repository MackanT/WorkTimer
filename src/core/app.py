"""
Application Core - Per-Client Instance Management

Each client gets their own AppCore instance with isolated state.
This enables true multi-client support with no shared state pollution.
"""

import logging
from collections import deque
from typing import Optional, Dict

import asyncio
from nicegui import app, ui

from ..config import ConfigLoader
from ..ui.elements import NavigationBar
from .events import PageEventBus

# Module-level storage for AppCore instances (per-client, by client ID)
_app_cores: Dict[str, "AppCore"] = {}


class AppCore:
    """
    Per-client application core.

    Contains all engines and services for a single client session.
    Stored in module-level dict keyed by client ID for per-client isolation.

    Usage:
        core = await AppCore.get_or_initialize()
        # Use core.event_bus, core.query_engine, etc.
    """

    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader
        self._load_configs()

        self._background_tasks = {}
        self._init_lock = asyncio.Lock()
        self._root_logger_attached = False

        self.nav_bar = NavigationBar(theme=self.theme)
        self.event_bus = PageEventBus()
        self.logger = self._setup_logger("AppCore")
        self.logger.info("Initializing new AppCore instance")

        self._setup_log_buffer()

        # Engines — initialized lazily
        self.query_engine = None
        self.devops_engine = None
        self.add_data_engine = None
        self._initialized = False
        self._devops_initialized = False
        self._devops_last_attempt = 0
        self._devops_no_customers = False

        self.logger.info("AppCore initialized")

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_configs(self):
        """Load all configuration files."""
        configs = self.config_loader.load_all()
        self.settings = configs["settings"]
        self.data_config = configs["data"]
        self.ui_config = self.config_loader.get_raw_dict("ui")
        self.tasks_config = self.config_loader.get_raw_dict("tasks")
        self.query_config = self.config_loader.get_raw_dict("query")
        self.devops_contacts = self.config_loader.get_raw_dict("devops_contacts")
        self.task_visuals = self.config_loader.get_raw_dict("task_visuals")
        self.debug = self.settings.debug_mode
        self.theme = self.config_loader.get_raw_dict("theme")

    # ── Logging ───────────────────────────────────────────────────────────────

    @property
    def devops_tags_config(self):
        return self.config_loader.configs["devops_tags"]

    # ── Logging ───────────────────────────────────────────────────────────────

    def _setup_log_buffer(self):
        """Set up in-memory log buffer for UI display."""
        self.log_buffer = deque(maxlen=500)

        def handler(
            message: str, level: str = "INFO", timestamp: str = "", logger: str = "App"
        ):
            self.log_buffer.append(
                {
                    "message": message,
                    "level": level,
                    "timestamp": timestamp,
                    "logger": logger,
                    "formatted": f"{timestamp} | {level:<8} | {logger:<9} :: {message}",
                }
            )

        self.event_bus.register("log_message", handler)

    def _setup_logger(self, name: str) -> logging.Logger:
        """Set up a named logger with EventBus handler."""
        from .events import EventBusLogHandler

        logger = logging.getLogger(name)

        # Early return if already configured
        if any(isinstance(h, EventBusLogHandler) for h in logger.handlers):
            return logger

        level = logging.DEBUG if self.debug else logging.INFO
        logger.setLevel(level)
        logger.propagate = False

        if self.event_bus:
            handler = EventBusLogHandler(self.event_bus)
            handler.setLevel(level)
            logger.addHandler(handler)

        return logger

    def _attach_root_logger_handler(self):
        """Attach EventBus + console handlers to root logger for global log capture."""
        if self._root_logger_attached:
            return

        from .events import EventBusLogHandler

        root = logging.getLogger()
        level = logging.DEBUG if self.debug else logging.INFO

        # Remove any stale EventBus handlers
        root.handlers = [
            h for h in root.handlers if not isinstance(h, EventBusLogHandler)
        ]

        # Console handler
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-12s :: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        console.setLevel(level)
        root.addHandler(console)

        # EventBus handler
        root.addHandler(EventBusLogHandler(self.event_bus))
        root.setLevel(level)

        self._root_logger_attached = True
        print(f"[AppCore] Logging initialized - Debug mode: {self.debug}")

    # ── Engine Initialization ─────────────────────────────────────────────────

    async def initialize_local_engines(self):
        """
        Initialize query and data engines.
        Called once per client on first page load.
        """
        if self._initialized:
            self.logger.debug("Engines already initialized, skipping")
            return

        self._attach_root_logger_handler()
        self.logger.info("Initializing engines...")

        try:
            from ..globals import QueryEngine, AddData

            db_logger = self._setup_logger("Database")
            self.query_engine = QueryEngine(
                file_name=self.settings.db_path, log_engine=db_logger
            )
            await self.query_engine.refresh()
            self.logger.info("Query engine initialized")

            self.add_data_engine = AddData(
                query_engine=self.query_engine, log_engine=self.logger
            )
            await self.add_data_engine.refresh()
            self.logger.info("Data engine initialized")

            self._initialized = True
            self.logger.info("Local engines initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize local engines: {e}")
            self.event_bus.notify(f"Initialization failed: {e}", type_="negative")
            raise

    async def initialize_devops(self):
        """
        Initialize or re-initialize DevOps engine.
        Safe to call multiple times — skips if already initialized.
        Retried on each page load until successful.
        """
        if not self._initialized:
            self.logger.debug("Local engines not ready — skipping DevOps init")
            return
        if self._devops_initialized:
            return

        # If no customers are configured, skip unless explicitly forced
        if getattr(self, "_devops_no_customers", False):
            self.logger.debug("No DevOps customers configured — skipping retry")
            return

        # Cooldown
        import time

        last_attempt = getattr(self, "_devops_last_attempt", 0)
        if time.time() - last_attempt < 60:
            self.logger.debug(
                f"DevOps retry cooldown — {int(60 - (time.time() - last_attempt))}s remaining"
            )
            return
        self._devops_last_attempt = time.time()

        # Quick internet check
        self.logger.info("Checking internet connectivity...")
        if not await self._check_internet():
            self.logger.warning("No internet — skipping DevOps init, will retry later")
            return

        self.logger.info("Internet available — proceeding with DevOps initialization")

        if not self.devops_engine:
            try:
                from ..globals import DevOpsEngine

                do_logger = self._setup_logger("DevOps")
                self.devops_engine = DevOpsEngine(
                    query_engine=self.query_engine, log_engine=do_logger
                )
            except Exception as e:
                self.logger.warning(f"Could not create DevOps engine: {e}")
                return

        await self._initialize_devops_background()

    async def _initialize_devops_background(self):
        """
        Run DevOps initialization with timeout.
        Sets _devops_initialized on success, False on failure — triggering retry next page load.
        """
        try:
            self.logger.info("Starting background DevOps initialization")
            await asyncio.wait_for(
                self.devops_engine.initialize(),
                timeout=30.0,
            )

            has_connections = (
                hasattr(self.devops_engine, "manager")
                and self.devops_engine.manager is not None
                and len(self.devops_engine.manager.clients) > 0
            )

            if has_connections:
                self._devops_initialized = True
                self._devops_no_customers = False
                self.logger.info(
                    f"DevOps initialized — {len(self.devops_engine.manager.clients)} customer(s) connected"
                )
            else:
                self._devops_initialized = False
                self._devops_no_customers = True
                self.logger.warning(
                    "DevOps initialize() completed but no customers configured — "
                    "will only retry when a customer is added"
                )

        except asyncio.TimeoutError:
            self._devops_initialized = False
            self._devops_no_customers = False
            self.logger.warning(
                "DevOps initialization timed out — will retry on next navigation"
            )
        except Exception as e:
            self._devops_initialized = False
            self._devops_no_customers = False
            self.logger.warning(f"DevOps initialization failed: {e}")

    def force_devops_reinit(self):
        """Force DevOps to retry — call this after adding a new DevOps customer."""
        self.logger.info("DevOps re-init forced — resetting state")
        self._devops_initialized = False
        self._devops_no_customers = False
        self._devops_last_attempt = 0
        self.devops_engine = None
        asyncio.create_task(self.initialize_devops())

    async def _check_internet(self) -> bool:
        """Quick DNS check to see if internet is available. Returns True/False in ~1s."""
        import socket

        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, lambda: socket.getaddrinfo("dev.azure.com", 443)
                ),
                timeout=3.0,
            )
            return True
        except Exception:
            return False

    # ── Client Management ─────────────────────────────────────────────────────

    @classmethod
    def get_or_create(cls, config_loader: Optional[ConfigLoader] = None) -> "AppCore":
        """
        Get existing AppCore for this client or create a new one.
        Keyed by NiceGUI client ID for per-client isolation.
        """
        from nicegui import context

        client_id = context.client.id

        if client_id in _app_cores:
            return _app_cores[client_id]

        core = cls(config_loader=config_loader or ConfigLoader())
        _app_cores[client_id] = core

        def cleanup():
            for tasks in core._background_tasks.values():
                for task in tasks:
                    if not task.done():
                        task.cancel()
            core._background_tasks.clear()
            _app_cores.pop(client_id, None)
            core.logger.debug(f"Client {client_id} disconnected, core cleaned up")

        context.client.on_disconnect(cleanup)
        return core

    @classmethod
    async def get_or_initialize(cls, config_loader=None) -> "AppCore":
        core = cls.get_or_create(config_loader=config_loader or get_config_loader())

        async with core._init_lock:
            if not core._initialized:
                await core.initialize_local_engines()
            if not core._devops_initialized:
                await core.initialize_devops()

        core.apply_theme()

        if not app.storage.client.get("navigation_created", False):
            core.nav_bar.render()

            async def on_navigate():
                if not core._devops_initialized:
                    core.logger.info("Navigation triggered DevOps retry...")
                    await core.initialize_devops()

            core.nav_bar.on_navigate = on_navigate

        return core

    # ── Background Tasks ──────────────────────────────────────────────────────

    def _setup_page_timers(self, page_name: str, *task_fns):
        """
        Cancel existing background tasks for a page and start new ones.

        Args:
            page_name: Unique identifier for the page (e.g. "time_tracking")
            *task_fns: Async functions to run as background tasks
        """
        for task in self._background_tasks.get(page_name, []):
            task.cancel()

        self._background_tasks[page_name] = [
            asyncio.create_task(fn()) for fn in task_fns
        ]
        self.logger.debug(
            f"Started {len(task_fns)} background task(s) for page '{page_name}'"
        )

    # ── Theme ─────────────────────────────────────────────────────────────────

    def apply_theme(self):
        """Apply Quasar color theme for current page context."""
        if not app.storage.client.get("theme_applied"):
            ui.dark_mode().enable()
            app.storage.client["theme_applied"] = True

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


# ── Module-level config singleton ─────────────────────────────────────────────

_config_loader: Optional[ConfigLoader] = None


def get_config_loader() -> ConfigLoader:
    """
    Get the shared config loader instance.
    Configs are immutable so sharing across clients is safe.
    """
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
        _config_loader.load_all()
    return _config_loader
