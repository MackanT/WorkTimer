"""
V2 Architecture Test Page

This page demonstrates all the key features of the V2 architecture:
- Multi-client isolation
- Thread-safe operations
- Event-driven updates
- Skeleton/populate pattern

Run main.py and navigate to http://localhost:8080/test
"""

from nicegui import ui, app
from datetime import datetime
import asyncio
from ..core import AppCore, get_config_loader
from ..ui.navigation import create_navigation
from ..services import DatabaseService


@ui.page("/test")
async def test_page():
    """Test page demonstrating V2 architecture features."""

    # Get app core (per-client instance)
    core = AppCore.get_or_create(get_config_loader())

    dark = ui.dark_mode()
    dark.enable()

    # Navigation
    create_navigation()

    # Setup debug keyboard handlers
    from ..ui.keyboard_handlers import setup_debug_keyboard_handlers

    setup_debug_keyboard_handlers(core)

    # Initialize if needed
    if not core._initialized:
        await core.initialize_engines()

    # Page title
    ui.page_title("WorkTimer V2 - Test Page")

    # ============== UI CONTAINERS ==============

    containers = {}

    with ui.column().classes("w-full p-8 gap-6"):
        # Header
        with ui.card().classes("w-full bg-primary"):
            ui.label("WorkTimer V2 Architecture Test").classes("text-3xl text-white")
            ui.label("This page demonstrates all V2 features").classes("text-white")

        # Test 1: Multi-Client Isolation
        with ui.card().classes("w-full"):
            ui.label("Test 1: Multi-Client Isolation").classes("text-xl font-bold")
            ui.label(
                "Open this page in multiple browsers/tabs. Each should have independent state."
            )

            with ui.row().classes("gap-4 items-center"):
                counter_input = ui.number(
                    label="Client Counter", value=app.storage.user.get("counter", 0)
                ).classes("w-32")

                def increment():
                    current = app.storage.user.get("counter", 0)
                    new_value = current + 1
                    app.storage.user["counter"] = new_value
                    counter_input.value = new_value
                    core.event_bus.notify(f"Counter: {new_value}", type_="info")

                ui.button("Increment", icon="add", on_click=increment)
                ui.label("← Click and check other tabs stay unchanged")

        # Test 2: Thread-Safe Notifications
        with ui.card().classes("w-full"):
            ui.label("Test 2: Thread-Safe Notifications").classes("text-xl font-bold")
            ui.label("Notifications work from background threads via EventBus")

            def test_notification():
                """Test notification from background thread."""

                def background_work():
                    import time

                    time.sleep(1)  # Simulate work

                    # This works because event_bus uses captured ui.context
                    core.event_bus.notify(
                        "Background task completed! ✓", type_="positive"
                    )

                core.event_bus.notify("Starting background task...", type_="info")

                import threading

                thread = threading.Thread(target=background_work, daemon=True)
                thread.start()

            ui.button(
                "Run Background Task", icon="schedule", on_click=test_notification
            )

        # Test 3: Skeleton/Populate Pattern
        with ui.card().classes("w-full"):
            ui.label("Test 3: Skeleton → Populate Pattern").classes("text-xl font-bold")
            ui.label("Page renders instantly, data loads in background")

            with ui.column().classes("w-full gap-2") as data_container:
                containers["data_display"] = data_container
                # Initially show loading skeleton
                with ui.card():
                    ui.spinner(size="sm")
                    ui.label("Loading data...")

            async def populate_data(data):
                """Called when data loads."""
                containers["data_display"].clear()

                with containers["data_display"]:
                    if not data:
                        ui.label("No data available").classes("text-grey")
                        return

                    for i, item in enumerate(data[:5]):  # Show first 5
                        with ui.card().classes("w-full"):
                            ui.label(f"Item {i + 1}: {item.get('name', 'Unknown')}")

            def load_sample_data():
                """Load data in background."""

                async def load():
                    # Simulate delay
                    await asyncio.sleep(1)

                    try:
                        # Try to load real data
                        result = core.query_engine.execute_query(
                            "SELECT * FROM customers LIMIT 5", ()
                        )
                        data = (
                            result.to_dict("records")
                            if hasattr(result, "to_dict")
                            else []
                        )
                    except:
                        # Fallback to sample data if DB not ready
                        data = [
                            {"name": "Sample Customer 1"},
                            {"name": "Sample Customer 2"},
                            {"name": "Sample Customer 3"},
                        ]

                    # Emit event
                    core.event_bus.emit("test_data_loaded", data=data)
                    core.event_bus.notify(f"Loaded {len(data)} items", type_="positive")

                db_service = DatabaseService(core)
                db_service.run_in_thread(load)

            # Register event
            core.event_bus.register("test_data_loaded", populate_data)

            ui.button("Reload Data", icon="refresh", on_click=load_sample_data)

            # Initial load
            load_sample_data()

        # Test 4: Event System
        with ui.card().classes("w-full"):
            ui.label("Test 4: Event System").classes("text-xl font-bold")
            ui.label("Multiple handlers can listen to same event")

            event_log = ui.log().classes("w-full h-32")

            # Register multiple handlers for same event
            async def log_event(message):
                timestamp = datetime.now().strftime("%H:%M:%S")
                event_log.push(f"[{timestamp}] {message}")

            async def show_notification(message):
                core.event_bus.notify(message, type_="info")

            core.event_bus.register("test_event", log_event)
            core.event_bus.register("test_event", show_notification)

            def trigger_event():
                message = (
                    f"Test event triggered at {datetime.now().strftime('%H:%M:%S')}"
                )
                core.event_bus.emit("test_event", message=message)

            ui.button("Trigger Event", icon="bolt", on_click=trigger_event)

        # Test 5: Per-Client State
        with ui.card().classes("w-full"):
            ui.label("Test 5: Per-Client State Storage").classes("text-xl font-bold")
            ui.label("Each client has isolated state in app.storage.user")

            with ui.column().classes("gap-2"):
                # Show current state
                state_display = ui.json_editor(
                    {
                        "mode": "view",
                        "statusBar": False,
                    }
                ).classes("w-full")

                def update_state_display():
                    # Get all user storage
                    user_data = dict(app.storage.user)
                    # Remove app_core to avoid circular reference issues
                    user_data.pop("app_core", None)
                    state_display.value = user_data

                update_state_display()

                with ui.row().classes("gap-2"):
                    key_input = ui.input(label="Key", placeholder="my_key")
                    value_input = ui.input(label="Value", placeholder="my_value")

                    def set_value():
                        if key_input.value and value_input.value:
                            app.storage.user[key_input.value] = value_input.value
                            update_state_display()
                            core.event_bus.notify(
                                f"Set {key_input.value} = {value_input.value}",
                                type_="positive",
                            )
                            key_input.value = ""
                            value_input.value = ""

                    ui.button("Set Value", on_click=set_value)

        # Test 6: Config Loading
        with ui.card().classes("w-full"):
            ui.label("Test 6: Configuration System").classes("text-xl font-bold")
            ui.label("Configs are loaded per-client but shared (immutable)")

            with ui.column().classes("gap-2"):
                ui.label(f"Database: {core.settings.db_name}").classes("text-mono")
                ui.label(f"Debug Mode: {core.settings.debug_mode}").classes("text-mono")
                ui.label(
                    f"UI Config Keys: {list(core.ui_config.keys())[:5]}..."
                ).classes("text-mono")

        # Test 7: Navigation Links
        with ui.card().classes("w-full"):
            ui.label("Test 7: Navigation").classes("text-xl font-bold")
            ui.label("Test multi-page navigation (each page has isolated state)")

            with ui.row().classes("gap-2"):
                ui.link("Time Tracking", "/").classes("text-lg")
                ui.link("Test Page (This)", "/test").classes("text-lg")

        # Info Section
        with ui.card().classes("w-full bg-grey-9"):
            ui.label("✓ All Tests Ready").classes("text-2xl text-positive")

            with ui.column().classes("gap-2"):
                ui.label("Key V2 Features Demonstrated:")
                ui.label("✓ Multi-client isolation via app.storage.user")
                ui.label("✓ Thread-safe ui.notify() via EventBus")
                ui.label("✓ Skeleton → Populate → Notify pattern")
                ui.label("✓ Event-driven architecture")
                ui.label("✓ Per-client AppCore with engines")
                ui.label("✓ Configuration system integration")

                ui.separator()

                ui.label("To test multi-client:").classes("font-bold")
                ui.label("1. Open this page in Chrome: http://localhost:8080/test")
                ui.label("2. Open same page in Firefox/Edge")
                ui.label("3. Increment counter in Chrome")
                ui.label("4. Verify Firefox counter stays unchanged")
