"""
Log Page

Display application logs with real-time updates via event bus.
Uses per-client AppCore and event-driven updates.
"""

from datetime import datetime

from nicegui import ui
from ..core.app import AppCore
from ..core.events import get_global_recent_logs
from ..helpers import UI_STYLES
from ..ui.elements import toolbar, toolbar_group, page_card
from ..ui.keyboard_handlers import setup_debug_keyboard_handlers


async def log_page():
    """Log page - displays application logs

    Note: No @ui.page decorator - accessed via SPA sub_pages in root.py
    Direct access to /log is handled by redirect in root.py
    """

    # Get or create AppCore for this client
    core = await AppCore.get_or_initialize()

    log_page_config = core.ui_config.get("log_page", {})
    log_colors = log_page_config.get('log', {}).get('log_colors', {})

    setup_debug_keyboard_handlers(core)

    def render_toolbar() -> tuple[ui.select, ui.button, ui.button]:
        """Render control panel - stable across data refreshes."""
        with toolbar(core.theme):
            with toolbar_group(core.theme, divider_after=False):
                ui.icon("terminal", size="md").classes(f"text-{core.theme.get('accent')}")
                ui.label("Application Log").classes(UI_STYLES.get_layout_classes("page_title"))
            ui.space()

            with toolbar_group(core.theme, divider_after=False):
                filter_select = (
                    ui.select(
                        options=["All", "AppCore", "Database", "DevOps", "EventBus"],
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

    filter_select, save_button, clear_button = render_toolbar()

    # Filter state
    selected_filter = {"value": "All"}

    with page_card(scrollable=False):
        log_widget = (
            ui.log(max_lines=None)
            .classes(UI_STYLES.get_widget_style("log_textarea")["base"] + " flex-1")
            .style(
                "min-height: 0; overflow-y: auto; overflow-x: auto; width: 100%; min-width: 100%;"
            )
        )

        def push_history(filter_value: str = "All"):
            """Render global + client-local log history (deduped, optionally filtered).

            Shared by the initial load and the filter handler so both show the
            same merged set — the old filter re-render dropped local entries.
            """
            seen_keys = set()
            try:
                merged = list(get_global_recent_logs()) + list(core.log_buffer)
            except Exception:
                merged = []
            for item in merged:
                if filter_value != "All":
                    if filter_value.lower() not in str(item.get("logger", "")).lower():
                        continue
                key = (
                    item.get("timestamp"),
                    item.get("logger"),
                    item.get("message"),
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                formatted = item.get("formatted") or (
                    f"{item.get('timestamp')} | {item.get('level', 'INFO'):<8} | "
                    f"{item.get('logger', 'App'):<9} :: {item.get('message', '')}"
                )
                color = log_colors.get(item.get("level", "INFO"), "white")
                try:
                    log_widget.push(formatted, classes=f"text-{color}")
                except Exception:
                    log_widget.push(formatted)

        # Load historical logs (no filter applied initially)
        push_history()

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
            color = log_colors.get(level, "white")
            try:
                log_widget.push(formatted, classes=f"text-{color}")
            except Exception:
                # Widget is dead/destroyed, ignore silently
                pass

        # register_unique: SPA navigation re-runs this page function without firing
        # on_disconnect — a plain register() would stack one handler per visit.
        core.event_bus.register_unique("log_message", on_new_log, key="log_page")

        # Re-apply filter handler when filter changes
        def apply_filter():
            try:
                # Update the selected filter value
                selected_filter["value"] = filter_select.value

                log_widget.clear()
                push_history(selected_filter["value"])
                ui.notify(
                    f"Filter applied: {selected_filter['value']}", type="info"
                )
            except Exception as e:
                core.logger.error(f"[Log] Error applying filter: {e}")

        # Bind filter change
        filter_select.on("update:model-value", apply_filter)

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
