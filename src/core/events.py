"""
Event System for Cross-Thread Communication

Enables safe UI updates from worker threads using NiceGUI's ui.context.
All UI operations from background threads MUST go through this system.
"""

import asyncio
from typing import Callable, Any, Optional
from nicegui import ui
import logging


class EventBus:
    """
    Central event bus for cross-thread communication.
    
    Handles safe execution of UI updates from worker threads by:
    1. Capturing the UI context when registering handlers
    2. Re-entering that context when events are triggered from threads
    3. Providing ui.notify() that works from any thread
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("EventBus")
        self._handlers = {}
        self._ui_context = None
        
    def capture_context(self):
        """
        Capture the current NiceGUI context.
        MUST be called from within a page function (inside @ui.page).
        """
        try:
            self._ui_context = ui.context.client
            self.logger.info("UI context captured successfully")
        except Exception as e:
            self.logger.error(f"Failed to capture UI context: {e}")
            
    def register(self, event_name: str, handler: Callable):
        """
        Register an event handler.
        
        Args:
            event_name: Name of the event to listen for
            handler: Async or sync function to call when event fires
        """
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)
        self.logger.debug(f"Registered handler for '{event_name}'")
        
    def emit(self, event_name: str, **kwargs):
        """
        Emit an event from any thread.
        
        This method is thread-safe and will execute handlers in the UI context.
        Can be called from worker threads, asyncio tasks, or the main thread.
        
        Args:
            event_name: Name of the event to trigger
            **kwargs: Data to pass to handlers
        """
        if not self._ui_context:
            self.logger.error(f"Cannot emit '{event_name}': No UI context captured")
            return
            
        handlers = self._handlers.get(event_name, [])
        if not handlers:
            self.logger.warning(f"No handlers registered for event '{event_name}'")
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
            asyncio.create_task(execute_handlers())
            
    def notify(
        self,
        message: str,
        type_: str = "info",
        position: str = "top",
        close_button: bool = True,
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
            self.logger.error(f"Cannot show notification: No UI context captured")
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
        except:
            pass  # Context will be captured manually if needed
