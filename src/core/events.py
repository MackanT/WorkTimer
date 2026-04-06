"""
Event System for Cross-Thread Communication

Enables safe UI updates from worker threads using NiceGUI's ui.context.
All UI operations from background threads MUST go through this system.
"""

import asyncio
from typing import Callable, Optional
from nicegui import ui
import logging
from datetime import datetime
from collections import deque

# Global recent logs buffer shared across clients/pages (helps when pages reload)
_GLOBAL_RECENT_LOGS = deque(maxlen=2000)


def get_global_recent_logs():
    """Return a copy of the global recent logs (oldest first)."""
    return list(_GLOBAL_RECENT_LOGS)


class EventBusLogHandler(logging.Handler):
    """
    Custom logging handler that emits log records to the EventBus.

    This bridges standard Python logging to the EventBus so logs appear in the UI.
    """

    def __init__(self, event_bus: "EventBus"):
        super().__init__()
        self.event_bus = event_bus

    def emit(self, record: logging.LogRecord):
        """Emit a log record to the event bus"""
        try:
            timestamp = datetime.fromtimestamp(record.created).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            # Mark record as forwarded so other handlers can skip duplicates
            try:
                record.__dict__["forwarded_to_ui"] = True
            except Exception:
                pass

            log_item = dict(
                message=record.getMessage(),
                level=record.levelname,
                timestamp=timestamp,
                logger=record.name,
            )
            # Store in per-event-bus recent logs buffer for replay
            try:
                self.event_bus._recent_logs.append(log_item)
            except Exception:
                pass
            # Store in global buffer so new pages/clients can see history
            try:
                _GLOBAL_RECENT_LOGS.append(log_item)
            except Exception:
                pass

            self.event_bus.emit("log_message", **log_item)
        except Exception:
            self.handleError(record)


class EventBus:
    """
    Central event bus for cross-thread communication.

    Common patterns:
    - emit(): Fire and forget events
    - register(): Listen for events
    - notify(): Show UI notifications from any thread
    - run_in_ui(): Execute arbitrary code in UI context
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("EventBus")
        self._handlers = {}
        self._ui_context = None
        self._recent_logs = deque(maxlen=500)
        # store the main asyncio loop when we capture context so background threads
        # can schedule coroutine execution into the running loop safely
        self._main_loop = None

    def capture_context(self):
        """Capture the current NiceGUI context.

        Safe to call multiple times; if the same client context is already
        captured this is a no-op to avoid repeated logs and duplicate captures.
        Additionally, capture and store the running asyncio loop when available
        so background threads can schedule coroutines into the main loop.
        """
        try:
            client = ui.context.client
            if self._ui_context is client:
                # Already captured the same UI context
                return
            self._ui_context = client
            try:
                # Store the main running loop if we're inside it
                self._main_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._main_loop = None
            self.logger.debug("UI context captured successfully")
        except Exception as e:
            self.logger.error(f"Failed to capture UI context: {e}")

    def register(self, event_name: str, handler: Callable):
        """
        Register an event handler.

        Args:
            event_name: Name of the event to listen for
            handler: Async or sync function to call when event fires

        Returns:
            The handler that was registered (useful for later unregistering)
        """
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)
        self.logger.debug(f"Registered handler for '{event_name}'")
        return handler

    def unregister(self, event_name: str, handler: Callable):
        """Unregister a previously registered handler for an event."""
        handlers = self._handlers.get(event_name, [])
        try:
            handlers.remove(handler)
            self.logger.debug(f"Unregistered handler for '{event_name}'")
        except ValueError:
            self.logger.debug(
                f"Attempted to unregister non-existent handler for '{event_name}'"
            )

    def emit(self, event_name: str, **kwargs):
        """
        Emit an event from any thread.

        Thread-safe and executes handlers in the UI context.

        Args:
            event_name: Name of the event to trigger
            **kwargs: Data to pass to handlers
        """
        if not self._ui_context:
            self.logger.error(f"Cannot emit '{event_name}': No UI context captured")
            return

        handlers = self._handlers.get(event_name, [])
        if not handlers:
            return

        async def execute_handlers():
            """Execute all handlers in the UI context"""
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(**kwargs)
                    else:
                        handler(**kwargs)
                except Exception as e:
                    self.logger.error(f"Error in handler for '{event_name}': {e}")

        # Execute in UI context
        with self._ui_context:
            try:
                # If we're already running inside an event loop, schedule as a task
                # If a running loop exists in this thread, schedule as a task
                asyncio.get_running_loop()
                asyncio.create_task(execute_handlers())
            except RuntimeError:
                # No running event loop in this thread. Try to schedule into the
                # main loop captured during `capture_context` using a thread-safe
                # coroutine submit. This allows worker threads to emit events.
                if self._main_loop and self._main_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        execute_handlers(), self._main_loop
                    )
                else:
                    # Final fallback: run the coroutine synchronously in a new loop
                    try:
                        asyncio.run(execute_handlers())
                    except Exception as e:
                        self.logger.error(
                            f"Failed to execute handlers synchronously: {e}"
                        )

    def run_in_ui(self, func: Callable, *args, **kwargs):
        """
        Run any function in the UI context.

        Useful for updating UI elements from background threads.

        Example:
            # From a worker thread:
            event_bus.run_in_ui(lambda: label.set_text("Updated!"))
        """
        if not self._ui_context:
            self.logger.error("Cannot run in UI: No UI context captured")
            return

        async def execute():
            try:
                if asyncio.iscoroutinefunction(func):
                    await func(*args, **kwargs)
                else:
                    func(*args, **kwargs)
            except Exception as e:
                self.logger.error(f"Error running function in UI context: {e}")

        with self._ui_context:
            try:
                # If a running loop exists in this thread, schedule as a task
                asyncio.get_running_loop()
                asyncio.create_task(execute())
            except RuntimeError:
                if self._main_loop and self._main_loop.is_running():
                    asyncio.run_coroutine_threadsafe(execute(), self._main_loop)
                else:
                    try:
                        asyncio.run(execute())
                    except Exception as e:
                        self.logger.error(
                            f"Failed to execute function synchronously in UI context: {e}"
                        )

    def notify(
        self,
        message: str,
        type_: str = "info",
        position: str = "bottom",
        close_button: bool = False,
    ):
        """
        Show a notification from any thread.

        This is the primary way to display notifications from worker threads.

        Args:
            message: Notification text
            type_: 'info', 'positive', 'negative', 'warning'
            position: 'top', 'bottom', 'left', 'right', 'center', etc.
            close_button: Whether to show a close button

        Example:
            # From a worker thread:
            event_bus.notify("Data loaded successfully!", type_="positive")
        """
        if not self._ui_context:
            self.logger.error("Cannot show notification: No UI context captured")
            return

        def show_notification():
            ui.notify(message, type=type_, position=position, close_button=close_button)

        # Execute in UI context
        with self._ui_context:
            show_notification()

    def clear_handlers(self, event_name: Optional[str] = None):
        """
        Clear event handlers.

        Args:
            event_name: If provided, clear only this event's handlers.
                       If None, clear all handlers.
        """
        if event_name:
            self._handlers.pop(event_name, None)
            self.logger.debug(f"Cleared handlers for '{event_name}'")
        else:
            self._handlers.clear()
            self.logger.debug("Cleared all event handlers")

    def get_recent_logs(self):
        """Return a list of recent logs (oldest first)."""
        return list(self._recent_logs)


class PageEventBus(EventBus):
    """
    Per-page event bus that auto-captures context on initialization.

    Use this when you want a separate event bus per page/client.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        super().__init__(logger)
        # Auto-capture context when created inside a page
        try:
            self.capture_context()
        except Exception:
            pass  # Context will be captured manually if needed
