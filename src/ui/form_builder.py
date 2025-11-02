"""
Entity Form Builder

Generic form builder that creates UI forms for any entity based on YAML configuration.
Replaces and improves upon helpers.build_generic_tab_panel() with better abstraction.
"""

from typing import Any, Callable, Dict, Optional

from nicegui import ui

from .. import helpers
from .data_registry import DataPrepRegistry


class EntityFormBuilder:
    """
    Generic form builder for any entity from YAML config.

    Builds Add/Update/Disable/Reenable forms based on config_ui.yml or config_tasks.yml.
    Uses DataPrepRegistry for data preparation and UI_STYLES for consistent styling.

    Usage:
        builder = EntityFormBuilder("customer", config_ui)
        widgets = builder.build_form(
            tab_type="Add",
            container_dict=my_containers,
            on_success=lambda: AD.refresh()
        )
    """

    def __init__(
        self,
        entity_name: str,
        config_source: Dict[str, Any],
        data_registry: Optional[DataPrepRegistry] = None,
    ):
        """
        Initialize the form builder for a specific entity.

        Args:
            entity_name: Name of the entity (e.g., "customer", "project", "task")
            config_source: Configuration dict (config_ui or config_tasks)
            data_registry: Optional DataPrepRegistry instance (uses global if None)
        """
        self.entity_name = entity_name
        self.config_source = config_source
        self.registry = data_registry or DataPrepRegistry
        self.UI_STYLES = helpers.UI_STYLES

        if entity_name not in config_source:
            raise ValueError(f"Entity '{entity_name}' not found in config")

        self.entity_config = config_source[entity_name]

    def build_form(
        self,
        tab_type: str,
        container_dict: Dict[str, Any],
        on_success_callback: Optional[Callable] = None,
        custom_handlers: Optional[Dict[str, Callable]] = None,
        render_functions: Optional[Dict[str, Callable]] = None,
        container_size: str = "md",
        layout_builder: Optional[Callable] = None,
        **prep_kwargs,
    ) -> Dict[str, Any]:
        """
        Build a form for the specified tab type.

        Args:
            tab_type: Type of tab ("Add", "Update", "Disable", "Reenable")
            container_dict: Dictionary storing tab containers (modified in-place)
            on_success_callback: Optional callback after successful save
            custom_handlers: Optional custom save handlers {function_name: handler}
            render_functions: Optional custom render functions for HTML fields
            container_size: Container size ("xs", "sm", "md", "lg", "xl", "xxl", "full")
            layout_builder: Optional custom layout function
            **prep_kwargs: Additional kwargs to pass to data prep function

        Returns:
            Dictionary of widget instances {field_name: widget}
        """
        # Get or create container
        container = container_dict.get(tab_type)
        if container is None:
            container = ui.element()
            container_dict[tab_type] = container
        container.clear()

        # Load tab-specific config
        tab_config = self.entity_config.get(tab_type.lower())
        if not tab_config:
            raise ValueError(
                f"Tab type '{tab_type}' not found for entity '{self.entity_name}'"
            )

        fields = tab_config["fields"]
        action = tab_config["action"]

        # Prepare data sources using registry
        data_sources = self._prepare_data(tab_type, fields, **prep_kwargs)

        # Build the form UI
        widgets = self._build_form_ui(
            container=container,
            tab_config=tab_config,
            fields=fields,
            action=action,
            data_sources=data_sources,
            custom_handlers=custom_handlers,
            render_functions=render_functions,
            container_size=container_size,
            layout_builder=layout_builder,
            on_success_callback=on_success_callback,
        )

        return widgets

    def _prepare_data(self, tab_type: str, fields: list, **kwargs) -> Dict[str, Any]:
        """
        Prepare data sources for the form using DataPrepRegistry.

        Args:
            tab_type: Type of tab
            fields: List of field configs
            **kwargs: Additional kwargs for data prep function

        Returns:
            Dictionary of data sources
        """
        # Try to get data from registry
        data_sources = self.registry.get_data(self.entity_name, tab_type, **kwargs)

        return data_sources or {}

    def _build_form_ui(
        self,
        container: ui.element,
        tab_config: Dict[str, Any],
        fields: list,
        action: Dict[str, str],
        data_sources: Dict[str, Any],
        custom_handlers: Optional[Dict[str, Callable]],
        render_functions: Optional[Dict[str, Callable]],
        container_size: str,
        layout_builder: Optional[Callable],
        on_success_callback: Optional[Callable],
    ) -> Dict[str, Any]:
        """
        Build the actual form UI elements.

        Uses helpers module for rendering logic (for now - can be refactored later).
        """
        # Get container styling
        max_width = self.UI_STYLES.get_container_width(container_size)
        card_classes = (
            f"{self.UI_STYLES.get_layout_classes('card')} max-w-{max_width}xl"
        )

        widgets = {}

        with container:
            with ui.card().classes(card_classes):
                # Assign dynamic options from data sources
                # Always call this even if data_sources is empty, because some fields
                # like date fields with options_source="today" don't need data_sources
                helpers.assign_dynamic_options(fields, data_sources=data_sources or {})

                # Build layout
                pending_relations = []
                rows_config = tab_config.get("rows")
                columns_config = tab_config.get("columns")

                if rows_config:
                    pending_relations = self._build_rows_layout(
                        rows_config, fields, widgets, render_functions
                    )
                elif columns_config:
                    pending_relations = self._build_columns_layout(
                        columns_config, fields, widgets, render_functions
                    )
                elif layout_builder:
                    widgets = layout_builder(fields, tab_config)
                else:
                    # Default simple column layout
                    with ui.column():
                        helpers.make_input_row(
                            fields, widgets=widgets, render_functions=render_functions
                        )

                # Bind parent-child relations
                if pending_relations:
                    helpers.bind_parent_relations(
                        widgets, pending_relations, render_functions, data_sources
                    )

                # Add save button
                save_data = helpers.SaveData(**action)
                helpers.add_generic_save_button(
                    save_data, fields, widgets, custom_handlers, on_success_callback
                )

        return widgets

    def _build_rows_layout(
        self,
        rows_config: list,
        fields: list,
        widgets: Dict[str, Any],
        render_functions: Optional[Dict[str, Callable]],
    ) -> list:
        """Build form layout with multiple rows."""
        pending_relations = []

        # First pass: check if any row has wide widgets
        # Fields can use either "name" or "field_id" as identifier
        has_wide_layout = any(
            self.UI_STYLES.is_wide_widget(field_config.get("type"))
            for row_fields in rows_config
            for field_name in row_fields
            if (
                field_config := next(
                    (
                        f
                        for f in fields
                        if f.get("name") == field_name
                        or f.get("field_id") == field_name
                    ),
                    None,
                )
            )
        )

        with ui.column().classes(self.UI_STYLES.get_layout_classes("form_column")):
            for row_fields in rows_config:
                # Get field configs for this row
                # Fields can use either "name" or "field_id" as identifier
                row_field_configs = [
                    field_config
                    for field_name in row_fields
                    if (
                        field_config := next(
                            (
                                f
                                for f in fields
                                if f.get("name") == field_name
                                or f.get("field_id") == field_name
                            ),
                            None,
                        )
                    )
                ]

                if not row_field_configs:
                    continue

                is_single_field = len(row_field_configs) == 1

                with ui.row().classes(self.UI_STYLES.get_layout_classes("form_row")):
                    # Determine widget size based on layout mode
                    widget_size = (
                        "full" if (has_wide_layout or is_single_field) else None
                    )

                    _, rels = helpers.make_input_row(
                        row_field_configs,
                        layout_mode=widget_size,
                        widgets=widgets,
                        defer_parent_wiring=True,
                        render_functions=render_functions,
                    )
                    pending_relations.extend(rels)

        return pending_relations

    def _build_columns_layout(
        self,
        columns_config: list,
        fields: list,
        widgets: Dict[str, Any],
        render_functions: Optional[Dict[str, Callable]],
    ) -> list:
        """Build form layout with multiple columns."""
        pending_relations = []

        with ui.row():
            for col_fields in columns_config:
                with ui.column():
                    # Get field configs for this column
                    # Fields can use either "name" or "field_id" as identifier
                    col_field_configs = [
                        field_config
                        for field_name in col_fields
                        if (
                            field_config := next(
                                (
                                    f
                                    for f in fields
                                    if f.get("name") == field_name
                                    or f.get("field_id") == field_name
                                ),
                                None,
                            )
                        )
                    ]

                    if col_field_configs:
                        _, rels = helpers.make_input_row(
                            col_field_configs,
                            widgets=widgets,
                            defer_parent_wiring=True,
                            render_functions=render_functions,
                        )
                        pending_relations.extend(rels)

        return pending_relations
