"""
Query Editor Page (V2)

SQL query editor with saved queries and result display.
Uses V2 architecture with per-client AppCore and event-driven updates.
"""

import asyncio
from nicegui import ui
from nicegui.events import KeyEventArguments
from ..core.app import AppCore, get_config_loader
from ..globals import SaveData
from .. import helpers


async def query_editor_page():
    """Query Editor page - for running SQL queries"""

    # Get or create AppCore for this client
    config_loader = get_config_loader()
    core = AppCore.get_or_create(config_loader)

    dark = ui.dark_mode()
    dark.enable()

    # Initialize engines if needed (first time only)
    if not core._initialized:
        await core.initialize_engines()

    # Shortcuts to engines and logger
    QE = core.query_engine
    LOG = core.logger
    config_query = core.query_config if hasattr(core, "query_config") else {}

    # Helper functions (adapted from legacy UI)
    def get_custom_queries():
        return QE.df[QE.df["is_default"] != 1]["query_name"].tolist()

    def validate_query_name(name: str, check_exists: bool = False) -> bool:
        if not name or not name.strip():
            ui.notify("Query name required", type="warning")
            LOG.warning("Query name is required!")
            return False
        existing = QE.df["query_name"].tolist()
        if check_exists and name in existing:
            ui.notify("Query name already exists", type="warning")
            LOG.warning(f"Query name '{name}' already exists!")
            return False
        return True

    async def validate_query_syntax(query: str) -> bool:
        try:
            await QE.query_db(query)
            return True
        except Exception:
            ui.notify("Query is invalid", type="warning")
            LOG.warning("Query syntax is invalid!")
            return False

    async def refresh_query_list():
        await QE.refresh()
        render_query_buttons()

    def create_query_dialog(
        title: str, input_type: str, options: list = None, on_confirm=None
    ):
        with ui.dialog() as popup:
            with ui.card().classes(helpers.UI_STYLES.get_widget_width("standard")):
                if input_type == "input":
                    name_widget = ui.input("Query Name").classes(
                        helpers.UI_STYLES.get_layout_classes("full_width")
                    )
                else:
                    name_widget = ui.select(
                        options=options or [], label="Existing Query"
                    ).classes(helpers.UI_STYLES.get_layout_classes("full_width"))

                async def on_button_click():
                    await on_confirm(popup, name_widget.value)

                with ui.row().classes(
                    helpers.UI_STYLES.get_layout_classes("full_row_between_centered")
                ):
                    ui.button(title, on_click=on_button_click).classes(
                        helpers.UI_STYLES.get_layout_classes("button_fixed")
                    )
                    ui.button("Cancel", on_click=popup.close).props("flat").classes(
                        helpers.UI_STYLES.get_layout_classes("button_fixed")
                    )
        popup.open()

    async def save_custom_query():
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
                LOG.info(f"Custom query '{name}' saved successfully!")
                await refresh_query_list()
                ui.notify(f"Query '{name}' saved!", type="positive")
            except Exception as e:
                LOG.error(f"Failed to save query '{name}': {e}")
                ui.notify(f"Error saving query: {e}", type="negative")
            finally:
                popup.close()

        create_query_dialog("Save", "input", on_confirm=perform_save)

    async def update_custom_query():
        custom_queries = get_custom_queries()
        if not custom_queries:
            ui.notify("No custom query exists", type="warning")
            LOG.warning("No custom query exists to update!")
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
                LOG.info(f"Custom query '{name}' updated successfully!")
                await refresh_query_list()
                ui.notify(f"Query '{name}' updated!", type="positive")
            except Exception as e:
                LOG.error(f"Failed to update query '{name}': {e}")
                ui.notify(f"Error updating query: {e}", type="negative")
            finally:
                popup.close()

        create_query_dialog(
            "Update", "select", options=custom_queries, on_confirm=perform_update
        )

    async def delete_custom_query():
        custom_queries = get_custom_queries()
        if not custom_queries:
            ui.notify("No custom query exists to delete", type="warning")
            return

        async def perform_delete(popup, name: str):
            if not validate_query_name(name):
                return
            try:
                await QE.function_db(
                    "execute_query", "delete from queries where query_name = ?", (name,)
                )
                LOG.info(f"Custom query '{name}' deleted successfully!")
                await refresh_query_list()
                ui.notify(f"Query '{name}' deleted!", type="positive")
            except Exception as e:
                LOG.error(f"Failed to delete query '{name}': {e}")
                ui.notify(f"Error deleting query: {e}", type="negative")
            finally:
                popup.close()

        create_query_dialog(
            "Delete", "select", options=custom_queries, on_confirm=perform_delete
        )

    async def show_row_edit_popup(row_data):
        table_name = helpers.extract_table_name(editor.value)
        if table_name not in ["time", "customers", "projects"]:
            ui.notify(
                f"Table '{table_name}' is not registered for editing!", type="negative"
            )
            LOG.warning(f"Table '{table_name}' is not editable!")
            return

        base_name = table_name.rstrip("s")
        primary_key = f"{base_name}_id"
        if primary_key not in row_data:
            ui.notify(
                f"Cannot find primary key '{primary_key}' in your query!",
                type="negative",
            )
            LOG.warning(f"Primary key '{primary_key}' not found in query results!")
            return

        pk_data = (primary_key, row_data[primary_key])
        table_row = await QE.function_db("get_query_edit_data", table_name, pk_data[1])
        if table_row.empty:
            ui.notify("Row not found", type="negative")
            LOG.warning(f"Row with {primary_key}={pk_data[1]} not found!")
            return
        table_row = table_row.iloc[0]

        data_sources = {}
        if table_name == "time":
            customer_id = table_row.get("customer_id", 0)
            projects = await QE.query_db(
                f"SELECT project_name FROM projects WHERE customer_id = {customer_id} AND is_current = 1"
            )
            data_sources["project_names"] = projects["project_name"].tolist()

        fields = config_query["query"][table_name]["fields"]
        action = config_query["query"][table_name]["action"]

        for field in fields:
            options_source = field.get("options_source")
            if options_source and options_source not in data_sources:
                data_sources[options_source] = table_row.get(options_source)
            if field["name"] == "project_name" and table_name == "time":
                field["default"] = table_row.get("project_name")

        helpers.assign_dynamic_options(fields, data_sources=data_sources)

        with ui.dialog() as popup:
            with ui.card().classes(helpers.UI_STYLES.get_widget_width("medium")):
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                # add_save_button from helpers is used in old UI; we reuse here
                from ..ui.query_editor import add_save_button as _add_save_button

                _add_save_button(save_data, fields, widgets, table_name, pk_data, popup)
            popup.open()

    async def on_cell_clicked(event):
        row_data = event.args["data"]
        await show_row_edit_popup(row_data)

    # Make this card full-bleed so it uses the whole viewport width like the legacy UI
    with ui.card().classes("w-screen -mx-8 px-8 my-4 p-6"):
        # Top row: presets/custom chips on the left, action buttons on the right
        with ui.row().classes("w-full justify-between items-center gap-2 mb-1"):
            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.label("Preset:").classes("text-sm font-semibold text-gray-400")
                preset_queries = ui.row().classes("gap-2 flex-wrap")
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

        # Execute button above editor
        with ui.row().classes(helpers.UI_STYLES.get_layout_classes("row_end")):
            ui.button(
                "Execute Query (f5)",
                icon="play_arrow",
                on_click=lambda: asyncio.create_task(execute_query()),
            ).props("color=primary size=sm")

        # Initial query: prefer 'time' preset if present
        initial_query = ""
        try:
            initial_query = QE.df[QE.df["query_name"] == "time"]["query_sql"].values[0]
        except Exception:
            initial_query = ""

        editor = ui.codemirror(
            initial_query, language="SQLite", theme="dracula"
        ).classes("h-48 w-full")

        grid_box = (
            ui.aggrid(
                {"columnDefs": [{"field": ""}], "rowData": []}, theme="alpine-dark"
            )
            .classes("h-96 w-full")
            .on("cellClicked", on_cell_clicked)
        )

        def render_query_chip(query_name, query_sql, is_default=True):
            ui.button(query_name, on_click=lambda: editor.set_value(query_sql)).props(
                "outline dense no-caps"
            ).classes("cursor-pointer").style("color: #9ca3af; border-color: #4b5563")

        def render_query_buttons():
            preset_queries.clear()
            custom_queries.clear()
            with preset_queries:
                for _, row in QE.df[QE.df["is_default"] == 1].iterrows():
                    render_query_chip(
                        row["query_name"], row["query_sql"], is_default=True
                    )
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

        asyncio.create_task(refresh_query_list())

    # Execute query on the grid and handle duplicate column names
    async def execute_query():
        query = editor.value
        try:
            df = await QE.query_db(query)
            if df is not None:
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

                grid_box.options["columnDefs"] = [
                    {"field": unique_cols[i], "headerName": str(col).lower()}
                    for i, col in enumerate(df.columns)
                ]
                df.columns = unique_cols
                grid_box.options["rowData"] = df.to_dict(orient="records")
                grid_box.update()
            else:
                LOG.info("Query executed successfully (no result set).")
        except Exception as e:
            error_msg = f"Query execution failed: {e}"
            LOG.error(error_msg)
            grid_box.options["columnDefs"] = [
                {"field": "error", "headerName": "❌ Error"}
            ]
            grid_box.options["rowData"] = [{"error": str(e)}]
            grid_box.update()

    # Clear editor and grid
    def clear_query():
        editor.set_value("")
        try:
            grid_box.options["columnDefs"] = [{"field": ""}]
            grid_box.options["rowData"] = []
            grid_box.update()
        except Exception:
            pass

    # Keyboard shortcuts
    def handle_key(e: KeyEventArguments):
        if e.key.f5 and not e.key.shift and e.action.keydown:
            asyncio.create_task(execute_query())
        elif e.modifiers.ctrl and e.key.enter and e.action.keydown:
            asyncio.create_task(execute_query())

    ui.keyboard(on_key=handle_key)

    # Execute initial query
    asyncio.create_task(execute_query())
