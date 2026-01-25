"""
Thread-Safe Service Layer

Provides safe wrappers around engines for worker thread operations.
All services handle ui.notify() via the event bus automatically.
"""

import asyncio
from typing import Optional, Any, Dict, List
from datetime import datetime
import threading
from ..core.app import AppCore


class BaseService:
    """
    Base class for all services.
    
    Provides common functionality like thread-safe execution and notifications.
    """
    
    def __init__(self, core: AppCore):
        self.core = core
        self.logger = core.logger
        self.event_bus = core.event_bus
        
    def run_in_thread(self, func, *args, **kwargs):
        """
        Execute a function in a background thread.
        
        The function can be sync or async. Results are not returned;
        use the event bus to communicate results back to the UI.
        
        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            threading.Thread: The thread object
        """
        def runner():
            try:
                if asyncio.iscoroutinefunction(func):
                    # Create new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(func(*args, **kwargs))
                    loop.close()
                else:
                    result = func(*args, **kwargs)
            except Exception as e:
                self.logger.error(f"Error in background task: {e}")
                self.event_bus.notify(
                    f"Background task failed: {e}",
                    type_="negative"
                )
                
        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        return thread


class DatabaseService(BaseService):
    """
    Thread-safe database operations service.
    
    Wraps query engine with proper thread handling and notifications.
    """
    
    async def get_customers(self) -> List[Dict[str, Any]]:
        """Get all customers from the database."""
        try:
            result = await self.core.query_engine.get_customers()
            return result.to_dict('records') if hasattr(result, 'to_dict') else []
        except Exception as e:
            self.logger.error(f"Failed to get customers: {e}")
            return []
            
    async def get_projects(self, customer_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get projects, optionally filtered by customer.
        
        Args:
            customer_id: If provided, only return projects for this customer
        """
        try:
            if customer_id:
                query = "SELECT * FROM projects WHERE customer_id = ? ORDER BY name"
                result = self.core.query_engine.execute_query(query, (customer_id,))
            else:
                query = "SELECT * FROM projects ORDER BY name"
                result = self.core.query_engine.execute_query(query, ())
            return result.to_dict('records') if hasattr(result, 'to_dict') else []
        except Exception as e:
            self.logger.error(f"Failed to get projects: {e}")
            return []
            
    def load_data_async(self, query: str, params: tuple = (), event_name: str = "data_loaded"):
        """
        Load data in a background thread and emit an event when done.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            event_name: Event to emit with results
        """
        async def load():
            try:
                result = self.core.query_engine.execute_query(query, params)
                data = result.to_dict('records') if hasattr(result, 'to_dict') else []
                
                # Emit event with results
                self.event_bus.emit(event_name, data=data)
                
                # Show notification
                self.event_bus.notify(
                    f"Loaded {len(data)} records",
                    type_="positive"
                )
            except Exception as e:
                self.logger.error(f"Failed to load data: {e}")
                self.event_bus.notify(
                    f"Failed to load data: {e}",
                    type_="negative"
                )
                
        return self.run_in_thread(load)


class DevOpsService(BaseService):
    """
    Thread-safe DevOps operations service.
    
    Handles Azure DevOps API calls with proper threading and user feedback.
    """
    
    def refresh_incremental_async(self):
        """
        Trigger an incremental DevOps refresh in the background.
        
        User will be notified when the refresh starts and completes.
        """
        async def refresh():
            try:
                self.event_bus.notify(
                    "Starting DevOps incremental refresh...",
                    type_="info"
                )
                
                await self.core.devops_engine.update_devops(incremental=True)
                
                self.event_bus.notify(
                    "DevOps refresh completed successfully!",
                    type_="positive"
                )
                
                # Emit event for UI to refresh
                self.event_bus.emit("devops_refreshed")
                
            except Exception as e:
                self.logger.error(f"DevOps refresh failed: {e}")
                self.event_bus.notify(
                    f"DevOps refresh failed: {e}",
                    type_="negative"
                )
                
        return self.run_in_thread(refresh)
        
    def refresh_full_async(self):
        """
        Trigger a full DevOps refresh in the background.
        
        This can take several minutes for large organizations.
        """
        async def refresh():
            try:
                self.event_bus.notify(
                    "Starting FULL DevOps refresh (this may take several minutes)...",
                    type_="warning"
                )
                
                await self.core.devops_engine.update_devops(incremental=False)
                
                self.event_bus.notify(
                    "Full DevOps refresh completed successfully!",
                    type_="positive"
                )
                
                # Emit event for UI to refresh
                self.event_bus.emit("devops_refreshed")
                
            except Exception as e:
                self.logger.error(f"Full DevOps refresh failed: {e}")
                self.event_bus.notify(
                    f"Full DevOps refresh failed: {e}",
                    type_="negative"
                )
                
        return self.run_in_thread(refresh)
        
    async def create_work_item_async(
        self,
        item_type: str,
        title: str,
        customer_id: int,
        **kwargs
    ):
        """
        Create a work item asynchronously.
        
        Args:
            item_type: 'epic', 'feature', or 'story'
            title: Work item title
            customer_id: Customer ID for DevOps connection
            **kwargs: Additional work item fields
        """
        try:
            self.event_bus.notify(
                f"Creating {item_type}...",
                type_="info"
            )
            
            # Get the appropriate creation method
            if item_type == 'epic':
                method = self.core.devops_engine.create_epic
            elif item_type == 'feature':
                method = self.core.devops_engine.create_feature
            elif item_type == 'story':
                method = self.core.devops_engine.create_user_story
            else:
                raise ValueError(f"Unknown work item type: {item_type}")
                
            result = await method(title=title, customer_id=customer_id, **kwargs)
            
            self.event_bus.notify(
                f"{item_type.capitalize()} created successfully!",
                type_="positive"
            )
            
            # Emit event with result
            self.event_bus.emit("work_item_created", result=result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to create {item_type}: {e}")
            self.event_bus.notify(
                f"Failed to create {item_type}: {e}",
                type_="negative"
            )
            raise


class TimerService(BaseService):
    """
    Thread-safe timer operations service.
    
    Handles time tracking with proper state management.
    """
    
    async def get_active_timers(self) -> List[Dict[str, Any]]:
        """Get all currently active timers."""
        try:
            query = """
                SELECT t.*, c.name as customer_name, p.name as project_name
                FROM time_entries t
                LEFT JOIN customers c ON t.customer_id = c.customer_id
                LEFT JOIN projects p ON t.project_id = p.project_id
                WHERE t.end_time IS NULL
                ORDER BY t.start_time DESC
            """
            result = self.core.query_engine.execute_query(query, ())
            return result.to_dict('records') if hasattr(result, 'to_dict') else []
        except Exception as e:
            self.logger.error(f"Failed to get active timers: {e}")
            return []
            
    async def start_timer(
        self,
        customer_id: int,
        project_id: int,
        task_id: Optional[int] = None,
        description: str = ""
    ):
        """Start a new timer."""
        try:
            # Implementation depends on your existing AddData logic
            # This is a placeholder showing the pattern
            
            self.event_bus.notify(
                "Timer started!",
                type_="positive"
            )
            
            # Emit event for UI to refresh
            self.event_bus.emit("timer_started")
            
        except Exception as e:
            self.logger.error(f"Failed to start timer: {e}")
            self.event_bus.notify(
                f"Failed to start timer: {e}",
                type_="negative"
            )
            raise
