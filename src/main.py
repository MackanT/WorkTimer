"""
WorkTimer - Main Application Entry Point

A NiceGUI-based time tracking application with Azure DevOps integration.
Manages customer/project time tracking, tasks, and reporting.
"""

import asyncio
import threading

from nicegui import ui

from .config import ConfigLoader
from .globals import (
    AddData,
    DevOpsEngine,
    DevOpsTag,
    GlobalRegistry,
    QueryEngine,
    UIRefreshEngine,
    setup_logger,
)
from .ui.app_layout import setup_ui

from dotenv import load_dotenv

from nicegui.events import KeyEventArguments


## Utility Functions ##
def run_async_task(func, *args, **kwargs):
    """
    Run any function (sync or async) in a separate thread.
    Useful for running background tasks without blocking the main event loop.

    Args:
        func: Function to run (can be sync or async)
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        threading.Thread: The daemon thread running the task
    """

    def runner():
        if asyncio.iscoroutinefunction(func):
            asyncio.run(func(*args, **kwargs))
        else:
            func(*args, **kwargs)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread


## Application Initialization ##
def _initialize_engines(settings, data_config):
    """Initialize all application engines and register them in GlobalRegistry"""
    # Initialize loggers using standard Python logging
    log = setup_logger("WorkTimer", debug=settings.debug_mode)
    log.info("Starting WorkTimer!")
    db_log = setup_logger("Database", debug=settings.debug_mode)
    do_log = setup_logger("DevOps", debug=settings.debug_mode)

    # Initialize database engine
    query_engine = QueryEngine(file_name=settings.db_name, log_engine=db_log)
    asyncio.run(query_engine.refresh())

    # Initialize data engine
    add_data = AddData(query_engine=query_engine, log_engine=log)
    asyncio.run(add_data.refresh())

    # Initialize DevOps engine
    devops_engine = DevOpsEngine(query_engine=query_engine, log_engine=do_log)
    print("INFO: Initializing DevOps engine...")
    asyncio.run(devops_engine.initialize())
    print("INFO: DevOps engine initialization completed")

    # Initialize UI refresh engine
    ui_engine = UIRefreshEngine(query_engine=query_engine, log_engine=log)
    print("INFO: UI refresh engine created")

    # Register all engines in GlobalRegistry
    GlobalRegistry.set("LOG", log)
    GlobalRegistry.set("QE", query_engine)
    GlobalRegistry.set("DO", devops_engine)
    GlobalRegistry.set("AD", add_data)
    GlobalRegistry.set("UI", ui_engine)
    GlobalRegistry.set("run_async_task", run_async_task)


def _register_configs(config_loader, data_config, settings):
    """Register all configuration objects in GlobalRegistry"""
    # Register configuration objects (as dicts for backward compatibility)
    GlobalRegistry.set("config_ui", config_loader.get_raw_dict("ui"))
    GlobalRegistry.set(
        "config_devops_contacts", config_loader.get_raw_dict("devops_contacts")
    )
    GlobalRegistry.set("config_tasks", config_loader.get_raw_dict("tasks"))
    GlobalRegistry.set(
        "config_task_visuals", config_loader.get_raw_dict("task_visuals")
    )
    GlobalRegistry.set("config_query", config_loader.get_raw_dict("query"))
    GlobalRegistry.set("MAIN_DB", settings.db_name)

    # Build DevOps tags list from config
    devops_tags = [DevOpsTag(**tag.model_dump()) for tag in data_config.devops_tags]
    GlobalRegistry.set("DEVOPS_TAGS", devops_tags)


def handle_key(e: KeyEventArguments):
    LOG = GlobalRegistry.get("LOG")
    if e.key == "f" and not e.action.repeat:
        if e.action.keyup:
            LOG.info("'f' key was released")
    elif e.key == "g" and not e.action.repeat:
        if e.action.keyup:
            LOG.debug("'g' key was released")
    if e.key == "h" and not e.action.repeat:
        if e.action.keyup:
            LOG.warning("'h' key was released")
    if e.key == "j" and not e.action.repeat:
        if e.action.keyup:
            LOG.error("'j' key was released")


def main():
    """Initialize and run the WorkTimer application"""
    # Load and validate all configuration
    load_dotenv()
    config_loader = ConfigLoader()
    configs = config_loader.load_all()

    settings = configs["settings"]
    data_config = configs["data"]

    # Initialize all engines
    _initialize_engines(settings, data_config)

    # Register configurations
    _register_configs(config_loader, data_config, settings)

    # DEBUG: Set up key event handling
    ui.keyboard(on_key=handle_key)

    # Disable F5 refresh in browser
    ui.add_head_html("""
    <script>
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F5') {
            e.preventDefault();
        }
    });
    </script>
    """)

    # Set up the UI
    setup_ui()


if __name__ in {"__main__", "__mp_main__"}:
    main()
    # @ui.page('/settings') # Example code for different names on different pages
    # def settings_page():
    #     ui.page_title('Settings')
    #     ui.favicon('static/settings_icon.png')
    #     ui.label('Settings page')
    ui.page_title("WorkTimer")
    ui.run(host="0.0.0.0", port=8080, favicon="icons//worktimer.ico")
