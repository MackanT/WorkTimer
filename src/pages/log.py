"""
Log Page

Display application logs with real-time updates via event bus.
Uses per-client AppCore and event-driven updates.
"""

from datetime import datetime
from typing import Tuple
from ..globals import LOG_COLORS

from nicegui import ui
from ..core.app import AppCore
from ..helpers import UI_STYLES

from ..ui.elements import toolbar, page_card

### TODO move out of here!
LOG_CARD_HEIGHT = "76vh"


async def log_page():
    """Log page - displays application logs
    
    Note: No @ui.page decorator - accessed via SPA sub_pages in root.py
    Direct access to /log is handled by redirect in root.py
    """

    # Get or create AppCore for this client
    core = await AppCore.get_or_initialize()

    from ..ui.keyboard_handlers import setup_debug_keyboard_handlers

    setup_debug_keyboard_handlers(core)

    def render_toolbar() -> Tuple[ui.select, ui.button, ui.button]:
        """Render control panel - stable across data refreshes."""
        with toolbar(core.theme):
            ui.icon("terminal", size="md").classes("text-blue-400")
            ui.label("Application Log").classes("text-h5 text-white font-medium")
            ui.space()

            filter_select = (
                ui.select(
                    options=[
                        "All",
                        "AppCore",
                        "Database",
                        "DevOps",
                        # "Main",
                        "EventBus",
                        # "Navigation",
                        # "TimeTracking",
                        # "QueryEditor",
                        # "AddData",
                        # "Tasks",
                        # "Info",
                    ],
                    value="All",
                    label="Filter by Source",
                )
                .classes("w-40")
                .props("dense")
            )

            save_button = (
                ui.button("Save to File", icon="download").props("flat").classes("h-9")
            )

            clear_button = (
                ui.button("Clear Log", icon="clear").props("flat").classes("h-9")
            )

        return filter_select, save_button, clear_button

    if not core:
        with page_card():
            ui.label("Log engine not available").classes(
                UI_STYLES.get_layout_classes("text_negative")
            )
        return

    filter_select, save_button, clear_button = render_toolbar()

    # Filter state
    selected_filter = {"value": "All"}

    with page_card():
        # Log display container with fixed width
        with ui.element().classes("w-full").style("width: 100%;"):
            log_widget = (
                ui.log(max_lines=None)
                .classes("w-full bg-[#282a36] text-white p-4 rounded-lg")
                .style(
                    f"height: {LOG_CARD_HEIGHT}; overflow-y: auto; overflow-x: auto; width: 100%; min-width: 100%;"
                )
            )

            # Load historical logs (no filter applied initially)
            from ..core.events import get_global_recent_logs

            seen = set()

            # Global logs (oldest first)
            try:
                for item in get_global_recent_logs():
                    key = (
                        item.get("timestamp"),
                        item.get("logger"),
                        item.get("message"),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    formatted = f"{item.get('timestamp')} | {item.get('level'):<8} | {item.get('logger'):<9} :: {item.get('message')}"
                    color = LOG_COLORS.get(item.get("level"), "white")
                    try:
                        log_widget.push(formatted, classes=f"text-{color}")
                    except Exception:
                        log_widget.push(formatted)
            except Exception:
                pass

            # Per-core buffer (in case some logs were local)
            try:
                for log_entry in core.log_buffer:
                    key = (
                        log_entry.get("timestamp"),
                        log_entry.get("logger"),
                        log_entry.get("message"),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    color = LOG_COLORS.get(log_entry["level"], "white")
                    try:
                        log_widget.push(log_entry["formatted"], classes=f"text-{color}")
                    except Exception:
                        log_widget.push(log_entry["formatted"])
            except Exception:
                pass

            # Register handler for NEW logs (only during this page visit)
            def on_new_log(
                message: str,
                level: str = "INFO",
                timestamp: str = "",
                logger: str = "App",
            ):
                # Check if client still exists before attempting UI update
                try:
                    from nicegui import context

                    if (
                        not context.client
                        or context.client.id not in context.client.instances
                    ):
                        return  # Client disconnected, skip silently
                except Exception:
                    return  # No context available, skip

                # Check filter
                if selected_filter["value"] != "All":
                    if selected_filter["value"].lower() not in logger.lower():
                        return  # Skip this log entry

                formatted = f"{timestamp} | {level:<8} | {logger:<9} :: {message}"
                color = LOG_COLORS.get(level, "white")
                try:
                    log_widget.push(formatted, classes=f"text-{color}")
                except Exception:
                    # Widget is dead/destroyed, ignore silently
                    pass

            core.event_bus.register("log_message", on_new_log)

            # Re-apply filter handler when filter changes
            def apply_filter():
                try:
                    # Update the selected filter value
                    selected_filter["value"] = filter_select.value

                    log_widget.clear()
                    from ..core.events import _GLOBAL_RECENT_LOGS

                    seen = set()
                    for log_entry in _GLOBAL_RECENT_LOGS:
                        # Apply filter
                        if selected_filter["value"] != "All":
                            logger_name = log_entry.get("logger", "")
                            if (
                                selected_filter["value"].lower()
                                not in logger_name.lower()
                            ):
                                continue

                        key = (
                            log_entry.get("timestamp"),
                            log_entry.get("logger"),
                            log_entry.get("message"),
                        )
                        if key in seen:
                            continue
                        seen.add(key)

                        # Format the log entry (might not have 'formatted' key)
                        if "formatted" in log_entry:
                            formatted = log_entry["formatted"]
                        else:
                            formatted = f"{log_entry.get('timestamp')} | {log_entry.get('level', 'INFO'):<8} | {log_entry.get('logger', 'App'):<9} :: {log_entry.get('message', '')}"

                        color = LOG_COLORS.get(log_entry.get("level", "INFO"), "white")
                        try:
                            log_widget.push(formatted, classes=f"text-{color}")
                        except Exception:
                            log_widget.push(formatted)
                    ui.notify(
                        f"Filter applied: {selected_filter['value']}", type="info"
                    )
                except Exception as e:
                    print(f"[Log] Error applying filter: {e}")

            # Bind filter change to apply_filter (single binding)
            filter_select.on("update:model-value", lambda: apply_filter())

            # Clear handler - clears widget only, not the buffer
            def clear_log():
                try:
                    log_widget.clear()
                    log_widget.push("--- Log cleared ---", classes="text-gray-400")
                except Exception:
                    pass
                ui.notify("Log display cleared", type="info")

            clear_button.on_click(clear_log)

            # Save to file handler
            def save_log_to_file():
                try:
                    # Get all logs from global buffer
                    from ..core.events import get_global_recent_logs

                    logs = get_global_recent_logs()

                    # Format logs as text
                    log_text = "\n".join(
                        [
                            f"{item.get('timestamp')} | {item.get('level'):<8} | {item.get('logger'):<9} :: {item.get('message')}"
                            for item in logs
                        ]
                    )

                    # Generate filename with timestamp
                    filename = (
                        f"worktimer_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    )

                    # Trigger download
                    ui.download(log_text.encode("utf-8"), filename)
                    ui.notify(f"Log saved to {filename}", type="positive")
                except Exception as e:
                    ui.notify(f"Error saving log: {e}", type="negative")

            save_button.on_click(save_log_to_file)

            # Cleanup handler when user navigates away or disconnects
            def cleanup():
                core.event_bus.unregister("log_message", on_new_log)
                core.logger.debug("Log page handler unregistered")

            ui.context.client.on_disconnect(cleanup)

        core.logger.info("Log page loaded")
