"""
Info Page (V2)

Display application information, configuration, and statistics.
Uses V2 architecture with per-client AppCore and event-driven updates.
"""

from nicegui import ui
from ..core.app import AppCore, get_config_loader
from ..ui.navigation import create_navigation


@ui.page("/info")
async def info_page():
    """Info page - displays application information"""

    # Get or create AppCore for this client
    config_loader = get_config_loader()
    core = AppCore.get_or_create(config_loader)

    dark = ui.dark_mode()
    dark.enable()

    # Navigation
    create_navigation()

    # Setup debug keyboard handlers
    from ..ui.keyboard_handlers import setup_debug_keyboard_handlers
    setup_debug_keyboard_handlers(core)

    if not core._initialized:
        await core.initialize_engines()

    # Main content
    with ui.column().classes("w-full p-4 gap-6"):
        ui.label("WorkTimer Information").classes("text-h4 mb-4")

        # Application Info
        with ui.card().classes("w-full"):
            ui.label("Application").classes("text-h6 mb-2")
            with ui.column().classes("gap-1"):
                ui.label("WorkTimer V2 - Time Tracking Application")
                ui.label("Architecture: Multi-client with per-client isolation")
                ui.label("Framework: NiceGUI with @ui.page() decorators")

        # Configuration Info
        with ui.card().classes("w-full"):
            ui.label("Configuration").classes("text-h6 mb-2")
            with ui.column().classes("gap-1"):
                settings = core.settings
                ui.label(f"Database: {settings.db_path}")
                ui.label(f"Debug Mode: {settings.debug_mode}")

                # Count configurations
                ui_config = core.config_loader.get_raw_dict("ui")
                tasks_config = core.config_loader.get_raw_dict("tasks")
                ui.label(f"UI Configurations: {len(ui_config)} sections")
                ui.label(f"Task Configurations: {len(tasks_config)} customers")

        # Database Statistics
        with ui.card().classes("w-full"):
            ui.label("Database Statistics").classes("text-h6 mb-2")
            stats_container = ui.column().classes("gap-1")

            async def load_stats():
                """Load and display database statistics"""
                try:
                    # Get counts
                    customers_df = await core.query_engine.get_customers()
                    projects_df = await core.query_engine.get_projects()

                    # Query for time entries
                    time_entries_df = await core.query_engine.query_db(
                        "SELECT COUNT(*) as count FROM time_entries"
                    )
                    time_entries_count = (
                        time_entries_df.iloc[0]["count"]
                        if len(time_entries_df) > 0
                        else 0
                    )

                    with stats_container:
                        ui.label(f"Customers: {len(customers_df)}")
                        ui.label(f"Projects: {len(projects_df)}")
                        ui.label(f"Time Entries: {time_entries_count}")

                except Exception as e:
                    with stats_container:
                        ui.label(f"Error loading statistics: {e}").classes(
                            "text-red-500"
                        )

            await load_stats()

        # DevOps Integration Status
        with ui.card().classes("w-full"):
            ui.label("Azure DevOps Integration").classes("text-h6 mb-2")
            devops_container = ui.column().classes("gap-1")

            async def load_devops_status():
                """Load and display DevOps connection status"""
                try:
                    # Check if DevOps is configured
                    has_devops = (
                        hasattr(core, "devops_engine")
                        and core.devops_engine is not None
                    )

                    with devops_container:
                        if has_devops:
                            ui.label("Status: ✓ Connected").classes("text-green-500")

                            # Get organization info from customers with PAT tokens
                            customers_df = await core.query_engine.get_customers()
                            customers_with_devops = customers_df[
                                customers_df["devops_pat"].notna()
                                & (customers_df["devops_pat"] != "")
                            ]

                            if len(customers_with_devops) > 0:
                                ui.label(
                                    f"Configured Customers: {len(customers_with_devops)}"
                                )
                                for _, row in customers_with_devops.iterrows():
                                    ui.label(
                                        f"  • {row['customer_name']} ({row['devops_org']})"
                                    )
                            else:
                                ui.label(
                                    "No customers configured with DevOps PAT tokens"
                                )
                        else:
                            ui.label("Status: Not configured").classes("text-gray-500")

                except Exception as e:
                    with devops_container:
                        ui.label(f"Error checking DevOps status: {e}").classes(
                            "text-red-500"
                        )

            await load_devops_status()

        # Architecture Info
        with ui.card().classes("w-full"):
            ui.label("V2 Architecture Components").classes("text-h6 mb-2")
            with ui.column().classes("gap-2"):
                ui.label("Core Components:").classes("font-bold")
                ui.label("  • AppCore: Per-client application state")
                ui.label("  • EventBus: Thread-safe UI updates")
                ui.label("  • ConfigLoader: YAML configuration management")

                ui.label("Services:").classes("font-bold mt-2")
                ui.label("  • DatabaseService: Thread-safe DB operations")
                ui.label("  • DevOpsService: Azure DevOps integration")
                ui.label("  • TimerService: Time tracking logic")

                ui.label("Pages:").classes("font-bold mt-2")
                ui.label("  • Time Tracking: Main time entry interface")
                ui.label("  • Data Input: Entity creation forms")
                ui.label("  • Query Editor: SQL query interface")
                ui.label("  • Log: Real-time log display")
                ui.label("  • Info: This page")

        # Actions
        with ui.card().classes("w-full"):
            ui.label("Actions").classes("text-h6 mb-2")
            with ui.row().classes("gap-2"):

                async def refresh_devops():
                    ui.notify("Starting DevOps refresh...", type="info")
                    try:
                        if core.devops_engine:
                            await core.devops_engine.update_devops(incremental=True)
                            ui.notify("DevOps refresh completed!", type="positive")
                        else:
                            ui.notify("DevOps not initialized", type="warning")
                    except Exception as e:
                        ui.notify(f"DevOps refresh failed: {e}", type="negative")

                ui.button(
                    "Refresh DevOps Data", icon="sync", on_click=refresh_devops
                ).props("color=primary")
                ui.button(
                    "Reload Configuration",
                    icon="refresh",
                    on_click=lambda: ui.notify("Not implemented yet", type="warning"),
                ).props("flat")
