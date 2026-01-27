"""
Log Page

Display application logs with real-time updates via event bus.
Uses per-client AppCore and event-driven updates.
"""

import logging
from ..globals import LOG_COLORS

from nicegui import ui
from ..core.app import AppCore, get_config_loader

from ..helpers import UI_STYLES


### TODO move out of here!
LOG_CARD_HEIGHT = "76vh"
LOG_CARD_MAX_WIDTH = "98vw"


async def log_page():
    """Log page - displays application logs"""

    # Get or create AppCore for this client
    config_loader = get_config_loader()
    core = AppCore.get_or_create(config_loader=config_loader)

    dark = ui.dark_mode()
    dark.enable()

    if not core:
        with ui.card().classes(UI_STYLES.get_layout_classes("full_width_padded")):
            ui.label("Log engine not available").classes(
                UI_STYLES.get_layout_classes("text_negative")
            )
        return

    with ui.card().classes(f"w-full max-w-[{LOG_CARD_MAX_WIDTH}] mx-auto my-4 p-6"):
        # Header with icon and title and controls
        with ui.row().classes("w-full items-center gap-3 mb-4"):
            ui.icon("terminal", size="md").classes("text-blue-400")
            ui.label("Application Log").classes("text-h5 text-white font-medium")
            ui.space()
            clear_button = (
                ui.button("Clear Log", icon="clear").props("flat").classes("h-9")
            )
            # auto_scroll_toggle = ui.switch("Auto-scroll", value=True).classes(
            #     "scale-90"
            # ) ### TODO implement auto-scroll

        # Log display container
        with ui.element().classes("w-full"):
            log_widget = ui.log(max_lines=None).classes(
                "w-full bg-[#282a36] text-white p-4 rounded-lg overflow-auto"
            )
            try:
                log_widget.style(f"height: {LOG_CARD_HEIGHT};")
            except Exception:
                pass

            # Load historical logs. Prefer global recent logs (survives page reloads),
            # but fall back to per-core buffer as well.
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
                formatted = f"{timestamp} | {level:<8} | {logger:<9} :: {message}"
                color = LOG_COLORS.get(level, "white")
                try:
                    log_widget.push(formatted, classes=f"text-{color}")
                except Exception:
                    # Widget is dead/destroyed, ignore silently
                    pass

            core.event_bus.register("log_message", on_new_log)

            # Clear handler - clears widget only, not the buffer
            def clear_log():
                try:
                    log_widget.clear()
                except Exception:
                    log_widget.push("--- Log cleared ---")
                ui.notify("Log display cleared", type="info")

            clear_button.on_click(clear_log)

            # Cleanup handler when user navigates away or disconnects
            def cleanup():
                core.event_bus.unregister("log_message", on_new_log)
                core.logger.debug("Log page handler unregistered")

            ui.context.client.on_disconnect(cleanup)

        core.logger.info("Log page loaded")

        # # Attach EventBus-driven handler that pushes log messages to this ui.log
        # def on_log_message(
        #     message: str,
        #     level: str = "INFO",
        #     timestamp: str = "",
        #     logger: str = "App",
        # ):
        #     # Format like LOG_FORMAT: "%(asctime)s | %(levelname)-8s | %(name)-9s :: %(message)s"
        #     formatted = f"{timestamp} | {level:<8} | {logger:<9} :: {message}"
        #     color = LOG_COLORS.get(level, "white")
        #     try:
        #         log_widget.push(formatted, classes=f"text-{color}")
        #     except Exception:
        #         # Fallback to plain push
        #         log_widget.push(formatted)

        # core.event_bus.register("log_message", on_log_message)
        # # Replay recent logs so the widget shows past messages
        # try:
        #     for item in core.event_bus.get_recent_logs():
        #         on_log_message(**item)
        # except Exception:
        #     pass
        # # Ensure we cleanup when page unmounted
        # ui.element("div").style("display:none").on(
        #     "unmounted",
        #     lambda: core.event_bus.unregister("log_message", on_log_message),
        # )

        # # Clear handler
        # def clear_log():
        #     try:
        #         log_widget.clear()
        #     except Exception:
        #         # Fallback: push a clear message
        #         log_widget.push("--- Log cleared ---")
        #     ui.notify("Log cleared", type="info")

        # clear_button.on_click(clear_log)

        # Log display using HTML for color formatting
        # log_lines = []
        # log_area = (
        #     ui.html("<div class='log-area'>Application log started...</div>")
        #     .classes("w-full font-mono text-sm bg-gray-900 text-white rounded p-2")
        #     .style("min-height: 400px; max-height: 600px; overflow-y: auto;")
        # )

    #     # Color map for log levels
    #     LEVEL_COLORS = {
    #         "DEBUG": "#8ecae6",
    #         "INFO": "#90ee90",
    #         "WARNING": "#ffd166",
    #         "ERROR": "#ff6f61",
    #         "CRITICAL": "#d90429",
    #     }
    #     # Color map for logger/component tags
    #     LOGGER_COLORS = {
    #         "Main": "#2196f3",
    #         "Query": "#9c27b0",
    #         "Devops": "#ff9800",
    #         "Database": "#4caf50",
    #         "Timer": "#607d8b",
    #     }

    #     def format_log_line(message, level, timestamp, logger):
    #         level_color = LEVEL_COLORS.get(level, "#90ee90")
    #         logger_color = LOGGER_COLORS.get(logger, "#bdbdbd")
    #         # Tag for logger/component
    #         logger_tag = f"<span style='background:{logger_color};color:#fff;padding:2px 8px;border-radius:6px;margin-right:6px;font-weight:bold;font-size:0.95em'>{logger}</span>"
    #         # Tag for level
    #         level_tag = (
    #             f"<span style='color:{level_color};font-weight:bold;'>{level}</span>"
    #         )
    #         # Timestamp
    #         ts = f"<span style='color:#aaa;'>{timestamp}</span>"
    #         # Message
    #         msg = f"<span style='color:#fff;'>{message}</span>"
    #         return f"<div style='margin-bottom:2px'>{ts} {logger_tag}{level_tag}: {msg}</div>"

    #     # Register handler for log events
    #     async def on_log_message(
    #         message: str, level: str = "INFO", timestamp: str = "", logger: str = "App"
    #     ):
    #         log_lines.append(format_log_line(message, level, timestamp, logger))
    #         # Keep only last 500 lines
    #         if len(log_lines) > 500:
    #             log_lines.pop(0)
    #         # Update UI content directly (Html element)
    #         log_area.content = "<div class='log-area'>" + "".join(log_lines) + "</div>"
    #         # Auto-scroll if enabled (not implemented for Html element)

    #     # Register and keep handler id for cleanup
    #     handler_id = core.event_bus.register("log_message", on_log_message)

    #     if not core._initialized:
    #         await core.initialize_engines()

    #     # Clear handler
    #     def clear_log():
    #         log_lines.clear()
    #         log_area.content = "<div class='log-area'>Application log cleared...</div>"
    #         ui.notify("Log cleared", type="info")

    #     clear_button.on_click(clear_log)

    #     # Unregister log handler on page leave to avoid client deleted errors
    #     # Workaround: use a hidden element with on('unmounted') to unregister
    #     ui.element("div").style("display:none").on(
    #         "unmounted", lambda: core.event_bus.unregister("log_message", handler_id)
    #     )

    #     # Instructions
    #     ui.label(
    #         "Log messages from all application components will appear here in real-time."
    #     ).classes("text-gray-500 text-sm mt-4")
