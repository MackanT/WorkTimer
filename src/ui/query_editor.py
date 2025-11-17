"""
Query Editor UI Module

Handles the SQL query editor interface including:
- Predefined and custom query management
- Query execution with results grid
- Query save/update/delete operations
- Row editing from query results
"""

import asyncio
from nicegui import ui
from nicegui.events import KeyEventArguments

from ..globals import GlobalRegistry, SaveData
from .. import helpers


def ui_query_editor():
    """SQL query editor with save/update/delete and result grid."""
    # Get global instances from registry
    QE = GlobalRegistry.get("QE")
    LOG = GlobalRegistry.get("LOG")

    # Get configs from registry
    config_query = (
        GlobalRegistry.get("config_query") if GlobalRegistry.get("config_query") else {}
    )

    # Get UI_STYLES from helpers
    UI_STYLES = helpers.UI_STYLES

    asyncio.run(QE.refresh())

    # ========================================================================
    # Helper Functions
    # ========================================================================

    def get_custom_queries():
        """Get list of custom (non-default) query names."""
        return QE.df[QE.df["is_default"] != 1]["query_name"].tolist()

    def validate_query_name(name: str, check_exists: bool = False) -> bool:
        """Validate query name is not empty and optionally check existence."""
        if not name or not name.strip():
            ui.notify("Query name required", color="negative")
            LOG.log_msg("WARNING", "Query name is required!")
            return False

        existing_names = QE.df["query_name"].tolist()
        if check_exists and name in existing_names:
            ui.notify("Query name already exists", color="negative")
            LOG.log_msg("WARNING", f"Query name '{name}' already exists!")
            return False

        return True

    async def validate_query_syntax(query: str) -> bool:
        """Validate SQL query syntax by attempting to execute it."""
        try:
            await QE.query_db(query)
            return True
        except Exception:
            ui.notify("Query is invalid", color="negative")
            LOG.log_msg("WARNING", "Query syntax is invalid!")
            return False

    async def refresh_query_list():
        """Refresh query list and update UI."""
        await QE.refresh()
        render_query_buttons()

    def create_query_dialog(
        title: str, input_type: str, options: list = None, on_confirm=None
    ):
        """Create a standardized dialog for query operations.

        Args:
            title: Dialog title
            input_type: 'input' for text input, 'select' for dropdown
            options: List of options for select input
            on_confirm: Async callback function to execute on confirm (receives popup and value)
        """
        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("standard")):
                if input_type == "input":
                    name_widget = ui.input("Query Name").classes(
                        UI_STYLES.get_layout_classes("full_width")
                    )
                else:  # select
                    name_widget = ui.select(
                        options=options or [], label="Existing Query"
                    ).classes(UI_STYLES.get_layout_classes("full_width"))

                async def on_button_click():
                    await on_confirm(popup, name_widget.value)

                with ui.row().classes(
                    UI_STYLES.get_layout_classes("full_row_between_centered")
                ):
                    ui.button(title, on_click=on_button_click).classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
                    ui.button("Cancel", on_click=popup.close).props("flat").classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )

        popup.open()

    # ========================================================================
    # Query Management Operations
    # ========================================================================

    async def save_custom_query():
        """Save current editor content as a new custom query."""
        query = editor.value
        if not await validate_query_syntax(query):
            return

        async def perform_save(popup, name: str):
            if not validate_query_name(name, check_exists=True):
                return

            try:
                await QE.function_db(
                    "execute_query",
                    "insert into queries (query_name, query_sql) values (?, ?)",
                    (name, query),
                )
                LOG.log_msg("INFO", f"Custom query '{name}' saved successfully!")
                await refresh_query_list()
                ui.notify(f"Query '{name}' saved!", color="positive")
            except Exception as e:
                error_msg = str(e)
                LOG.log_msg("ERROR", f"Failed to save query '{name}': {error_msg}")
                ui.notify(f"Error saving query: {error_msg}", color="negative")
            finally:
                popup.close()

        create_query_dialog("Save", "input", on_confirm=perform_save)

    async def update_custom_query():
        """Update an existing custom query with current editor content."""
        custom_queries = get_custom_queries()
        if not custom_queries:
            ui.notify("No custom query exists", color="negative")
            LOG.log_msg("WARNING", "No custom query exists to update!")
            return

        query = editor.value
        if not await validate_query_syntax(query):
            return

        async def perform_update(popup, name: str):
            if not validate_query_name(name):
                return

            try:
                await QE.function_db(
                    "execute_query",
                    "update queries set query_sql = ? where query_name = ?",
                    (query, name),
                )
                LOG.log_msg("INFO", f"Custom query '{name}' updated successfully!")
                await refresh_query_list()
                ui.notify(f"Query '{name}' updated!", color="positive")
            except Exception as e:
                error_msg = str(e)
                LOG.log_msg("ERROR", f"Failed to update query '{name}': {error_msg}")
                ui.notify(f"Error updating query: {error_msg}", color="negative")
            finally:
                popup.close()

        create_query_dialog(
            "Update", "select", options=custom_queries, on_confirm=perform_update
        )

    async def delete_custom_query():
        """Delete an existing custom query."""
        custom_queries = get_custom_queries()
        if not custom_queries:
            ui.notify("No custom query exists to delete", color="negative")
            return

        async def perform_delete(popup, name: str):
            if not validate_query_name(name):
                return

            try:
                await QE.function_db(
                    "execute_query",
                    "delete from queries where query_name = ?",
                    (name,),
                )
                LOG.log_msg("INFO", f"Custom query '{name}' deleted successfully!")
                await refresh_query_list()
                ui.notify(f"Query '{name}' deleted!", color="positive")
            except Exception as e:
                error_msg = str(e)
                LOG.log_msg("ERROR", f"Failed to delete query '{name}': {error_msg}")
                ui.notify(f"Error deleting query: {error_msg}", color="negative")
            finally:
                popup.close()

        create_query_dialog(
            "Delete", "select", options=custom_queries, on_confirm=perform_delete
        )

    # ========================================================================
    # Row Edit Popup
    # ========================================================================

    def add_save_button(save_data, fields, widgets, table_name, pk_data, popup):
        """Add save button for row editing using centralized handler."""

        def close_popup():
            popup.close()

        # Add buttons in a row
        with ui.row().classes(
            UI_STYLES.get_layout_classes("row_end")
            + " "
            + UI_STYLES.get_layout_classes("row_gap_2")
        ):
            # Use centralized save button with additional_kwargs for table_name and pk_data
            async def _on_success_close():
                try:
                    popup.close()
                except Exception:
                    pass

            helpers.add_generic_save_button(
                save_data=save_data,
                fields=fields,
                widgets=widgets,
                custom_handlers=None,
                on_success_callback=_on_success_close,
                additional_kwargs={"table_name": table_name, "pk_data": pk_data},
                button_classes=UI_STYLES.get_layout_classes("button_fixed"),
            )

            # Add cancel button
            ui.button("Cancel", on_click=close_popup).props("flat").classes(
                UI_STYLES.get_layout_classes("button_fixed")
            )

    # ========================================================================
    # Query Button Rendering
    # ========================================================================

    # Top row: Preset queries on left, management buttons on right
    with ui.row().classes("w-full justify-between items-center gap-2 mb-1"):
        # Left side: Preset queries
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.label("Preset:").classes("text-sm font-semibold text-gray-400")
            preset_queries = ui.row().classes("gap-2 flex-wrap")

        # Right side: Management buttons (styled like To-Do view toggle)
        with ui.row().classes("gap-1"):
            ui.button(icon="save", on_click=save_custom_query).props(
                "flat dense color=primary"
            ).tooltip("Save Query")
            ui.button(icon="edit", on_click=update_custom_query).props(
                "flat dense color=primary"
            ).tooltip("Update Query")
            ui.button(icon="delete", on_click=delete_custom_query).props(
                "flat dense color=negative"
            ).tooltip("Delete Query")

    # Custom queries section - separate row below
    with ui.row().classes("items-center gap-2 flex-wrap mb-3"):
        ui.label("Custom:").classes("text-sm font-semibold text-gray-400")
        custom_queries = ui.row().classes("gap-2 flex-wrap")

    def render_query_chip(query_name, query_sql, is_default=True):
        """Render a single query as a clickable chip."""
        # Subtle outline button
        ui.button(
            query_name,
            on_click=lambda: editor.set_value(query_sql),
        ).props("outline dense no-caps").classes("cursor-pointer").style(
            "color: #9ca3af; border-color: #4b5563"
        )

    def render_query_buttons():
        """Render all preset and custom query chips."""
        preset_queries.clear()
        custom_queries.clear()

        with preset_queries:
            for _, row in QE.df[QE.df["is_default"] == 1].iterrows():
                render_query_chip(row["query_name"], row["query_sql"], is_default=True)

        with custom_queries:
            custom_df = QE.df[QE.df["is_default"] != 1]
            if custom_df.empty:
                ui.label("No custom queries yet").classes(
                    "text-xs text-gray-500 italic"
                )
            else:
                for _, row in custom_df.iterrows():
                    render_query_chip(
                        row["query_name"], row["query_sql"], is_default=False
                    )

    render_query_buttons()

    async def show_row_edit_popup(row_data):
        """Show popup for editing a row from query results."""
        # Extract table name from query
        table_name = helpers.extract_table_name(editor.value)

        # Validate table is editable
        if table_name not in ["time", "customers", "projects"]:
            ui.notify(
                f"Table '{table_name}' is not registered for editing!", color="negative"
            )
            LOG.log_msg("WARNING", f"Table '{table_name}' is not editable!")
            return

        # Determine primary key column
        base_name = table_name.rstrip("s")  # Remove trailing 's' if present
        primary_key = f"{base_name}_id"

        if primary_key not in row_data:
            ui.notify(
                f"Cannot find primary key '{primary_key}' in your query!",
                color="negative",
            )
            LOG.log_msg(
                "WARNING", f"Primary key '{primary_key}' not found in query results!"
            )
            return

        pk_data = (primary_key, row_data[primary_key])

        table_row = await QE.function_db("get_query_edit_data", table_name, pk_data[1])
        if table_row.empty:
            ui.notify("Row not found", color="negative")
            LOG.log_msg("WARNING", f"Row with {primary_key}={pk_data[1]} not found!")
            return

        table_row = table_row.iloc[0]

        data_sources = {}

        # Special handling for time table (needs project dropdown)
        if table_name == "time":
            customer_id = table_row.get("customer_id", 0)
            projects = await QE.query_db(
                f"SELECT project_name FROM projects WHERE customer_id = {customer_id} AND is_current = 1"
            )
            data_sources["project_names"] = projects["project_name"].tolist()

        # Get field configuration
        fields = config_query["query"][table_name]["fields"]
        action = config_query["query"][table_name]["action"]

        # Populate field options from current row data (don't overwrite existing data_sources)
        for field in fields:
            options_source = field.get("options_source")
            if options_source and options_source not in data_sources:
                data_sources[options_source] = table_row.get(options_source)
            if field["name"] == "project_name" and table_name == "time":
                field["default"] = table_row.get("project_name")

        helpers.assign_dynamic_options(fields, data_sources=data_sources)

        # Create edit popup
        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("medium")):
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets, table_name, pk_data, popup)
            popup.open()

    # ========================================================================
    # Cell Click Handler
    # ========================================================================

    async def on_cell_clicked(event):
        """Handle grid cell clicks to show row edit popup."""
        row_data = event.args["data"]
        await show_row_edit_popup(row_data)

    # ========================================================================
    # Query Editor UI Components
    # ========================================================================

    # Execute button above editor (replaces label)
    with ui.row().classes(UI_STYLES.get_layout_classes("row_end")):
        ui.button(
            "Execute Query (f5)",
            icon="play_arrow",
            on_click=lambda: asyncio.create_task(execute_query()),
        ).props("color=primary size=sm")

    # Get initial query (default 'time' query)
    initial_query = QE.df[QE.df["query_name"] == "time"]["query_sql"].values[0]

    # SQL editor with syntax highlighting
    editor = ui.codemirror(
        initial_query,
        language="SQLite",
        theme="dracula",
    ).classes("h-48 w-full")

    # Results grid with row click editing
    grid_box = (
        ui.aggrid(
            {
                "columnDefs": [{"field": ""}],
                "rowData": [],
            },
            theme="alpine-dark",
        )
        .classes("h-96 w-full")
        .on("cellClicked", on_cell_clicked)
    )

    # ========================================================================
    # Query Execution
    # ========================================================================

    async def execute_query():
        """Execute the current SQL query and display results in grid."""
        query = editor.value
        try:
            df = await QE.query_db(query)
            if df is not None:
                # Handle duplicate column names by adding suffixes
                cols = df.columns.tolist()
                seen = {}
                unique_cols = []
                for col in cols:
                    col_lower = str(col).lower()
                    if col_lower in seen:
                        seen[col_lower] += 1
                        unique_cols.append(f"{col_lower}_{seen[col_lower]}")
                    else:
                        seen[col_lower] = 0
                        unique_cols.append(col_lower)

                # Update grid with deduplicated column names
                grid_box.options["columnDefs"] = [
                    {"field": unique_cols[i], "headerName": str(col).lower()}
                    for i, col in enumerate(df.columns)
                ]
                # Rename DataFrame columns to match unique names
                df.columns = unique_cols
                grid_box.options["rowData"] = df.to_dict(orient="records")
                grid_box.update()
            else:
                LOG.log_msg("INFO", "Query executed successfully (no result set).")
        except Exception as e:
            error_msg = f"Query execution failed: {e}"
            LOG.log_msg("ERROR", error_msg)
            # Show error in grid
            grid_box.options["columnDefs"] = [
                {"field": "error", "headerName": "❌ Error"}
            ]
            grid_box.options["rowData"] = [{"error": str(e)}]
            grid_box.update()

    # Execute initial query on load
    asyncio.run(execute_query())

    def handle_key(e: KeyEventArguments):
        """Handle keyboard shortcuts - F5 to execute query."""
        if e.key.f5 and not e.key.shift and e.action.keydown:
            asyncio.create_task(execute_query())

    ui.keyboard(on_key=handle_key)
