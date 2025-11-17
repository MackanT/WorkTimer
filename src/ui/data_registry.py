"""
Data Preparation Registry

Central registry for all data preparation functions used across UI modules.
Allows each module to register entity-specific data prep logic and retrieve it dynamically.
"""

from typing import Any, Callable, Dict, Tuple


class DataPrepRegistry:
    """
    Registry for data preparation functions.
    
    Allows UI modules to register functions that prepare data for forms
    based on entity type and tab type (Add/Update/Disable/Reenable).
    
    Usage:
        # Registration (in module init or function scope)
        @DataPrepRegistry.register("customer", "Add")
        def prep_customer_add_data(AD, **kwargs):
            return {"date": None}
        
        # Retrieval
        data = DataPrepRegistry.get_data("customer", "Add", AD=ad_instance)
    """
    
    _handlers: Dict[Tuple[str, str], Callable] = {}
    
    @classmethod
    def register(cls, entity_name: str, tab_type: str) -> Callable:
        """
        Decorator to register a data preparation function.
        
        Args:
            entity_name: Name of the entity (e.g., "customer", "project", "task")
            tab_type: Type of tab (e.g., "Add", "Update", "Disable", "Reenable")
            
        Returns:
            Decorator function
            
        Example:
            @DataPrepRegistry.register("customer", "Update")
            def prep_customer_update(AD, **kwargs):
                # Prepare data for customer update form
                return {"customer_data": [...], "org_url": {...}}
        """
        def decorator(func: Callable) -> Callable:
            key = (entity_name.lower(), tab_type.lower())
            cls._handlers[key] = func
            return func
        return decorator
    
    @classmethod
    def register_function(cls, entity_name: str, tab_type: str, func: Callable) -> None:
        """
        Register a function directly (without decorator).
        
        Args:
            entity_name: Name of the entity
            tab_type: Type of tab
            func: Function to register
        """
        key = (entity_name.lower(), tab_type.lower())
        cls._handlers[key] = func
    
    @classmethod
    def get_data(cls, entity_name: str, tab_type: str, **kwargs) -> Dict[str, Any]:
        """
        Get prepared data for a specific entity and tab type.
        
        Args:
            entity_name: Name of the entity (e.g., "customer", "project")
            tab_type: Type of tab (e.g., "Add", "Update")
            **kwargs: Arguments to pass to the data prep function
            
        Returns:
            Dictionary of prepared data (field_name -> options/values)
            Returns empty dict if no handler registered
            
        Example:
            data = DataPrepRegistry.get_data("customer", "Update", AD=ad_instance)
            # Returns: {"customer_data": [...], "org_url": {...}, ...}
        """
        key = (entity_name.lower(), tab_type.lower())
        handler = cls._handlers.get(key)
        
        if handler:
            return handler(**kwargs)
        
        # No handler found - return empty dict
        return {}
    
    @classmethod
    def has_handler(cls, entity_name: str, tab_type: str) -> bool:
        """
        Check if a handler is registered for the given entity/tab combination.
        
        Args:
            entity_name: Name of the entity
            tab_type: Type of tab
            
        Returns:
            True if handler exists, False otherwise
        """
        key = (entity_name.lower(), tab_type.lower())
        return key in cls._handlers
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered handlers (useful for testing)."""
        cls._handlers.clear()
    
    @classmethod
    def list_handlers(cls) -> Dict[Tuple[str, str], str]:
        """
        List all registered handlers.
        
        Returns:
            Dictionary mapping (entity, tab_type) to function name
        """
        return {
            key: func.__name__
            for key, func in cls._handlers.items()
        }
