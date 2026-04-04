"""
Query Editor Page

SQL query editor with saved queries and result display.
Uses V2 architecture with per-client AppCore and event-driven updates.
"""

import asyncio
from typing import Tuple
from nicegui import ui, app
from nicegui.events import KeyEventArguments
from ..core.app import AppCore
from ..globals import SaveData
from .. import helpers
from ..ui.keyboard_handlers import setup_debug_keyboard_handlers
from ..ui.elements import toolbar, toolbar_group, page_card, entity_card_header
from ..ui.dynamic_widgets import WIDGET_CLASSES


async def query_editor_page():
    """Query Editor page - for running SQL queries

    Note: No @ui.page decorator - accessed via SPA sub_pages in root.py
    Direct access to /query_editor is handled by redirect in root.py
    """

    core = await AppCore.get_or_initialize()

    setup_debug_keyboard_handlers(core)

    if "query_editor_query" not in app.storage.user:
        app.storage.user["query_editor_query"] = "time"

    # Shortcuts to engines and logger
    QE = core.query_engine
    LOG = core.logger

    config_query = core.query_config if hasattr(core, "query_config") else {}

    # ========================================================================
    # Helper Functions
    # ========================================================================
    def _get_custom_queries() -> list:
        return QE.df[QE.df["is_default"] != 1]["query_name"].tolist()

    def _validate_query_name(name: str, check_exists: bool = False) -> bool:
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

    async def _validate_query_syntax(query: str) -> bool:
        try:
            await QE.query_db(query)
            return True
        except Exception:
            ui.notify("Query is invalid", type="warning")
            LOG.warning("Query syntax is invalid!")
            return False

    async def refresh_query_list() -> None:
        await QE.refresh()
        render_query_buttons()

    def _add_save_button(
        save_data, fields, widgets, table_name, pk_data, popup, query_engine
    ) -> None:
        """Add save button for row editing"""

        async def on_save():
            """Handle save operation using query engine."""
            required_fields = [
                field["name"] for field in fields if not field.get("optional", False)
            ]
            if not helpers.check_input(widgets, required_fields):
                return

            kwargs = {}
            for field in fields:
                field_name = field["name"]
                if field_name in widgets:
                    kwargs[field_name] = widgets[field_name].value

            kwargs["table_name"] = table_name
            kwargs["pk_data"] = pk_data

            try:
                await query_engine.function_db(save_data.function, **kwargs)
                msg_1, msg_2 = helpers.print_success(
                    table_name, save_data.main_param, save_data.main_action, widgets
                )
                LOG.info(msg_1)
                if msg_2:
                    LOG.info(msg_2)

                popup.close()

                try:
                    core.event_bus.emit("ui_refresh_requested")
                except Exception:
                    pass

            except Exception as e:
                LOG.error(f"Error saving row: {e}")
                ui.notify(f"Error saving: {str(e)}", type="negative")

        def close_popup():
            popup.close()

        with ui.row().classes(
            helpers.UI_STYLES.get_layout_classes("row_end")
            + " "
            + helpers.UI_STYLES.get_layout_classes("row_gap_2")
        ):
            ui.button(save_data.button_name, on_click=on_save).props("flat").classes(
                helpers.UI_STYLES.get_layout_classes("button_fixed")
            )
            ui.button("Cancel", on_click=close_popup).props("flat").classes(
                helpers.UI_STYLES.get_layout_classes("button_fixed")
            )

    def render_query_buttons() -> None:
        preset_queries.clear()
        custom_queries.clear()
        with preset_queries:
            for _, row in QE.df[QE.df["is_default"] == 1].iterrows():
                render_query_chip(row["query_name"], row["query_sql"], is_default=True)
        with custom_queries:
            custom_df = QE.df[QE.df["is_default"] != 1]
            if custom_df.empty:
                ui.label("No custom queries yet").classes(
                    helpers.UI_STYLES.get_layout_classes("muted_text_xs_italic")
                )
            else:
                for _, row in custom_df.iterrows():
                    render_query_chip(
                        row["query_name"], row["query_sql"], is_default=False
                    )

    def render_query_chip(
        query_name: str, query_sql: str, is_default: bool = True
    ) -> None:
        ui.button(query_name, on_click=lambda: editor.set_value(query_sql)).props(
            "outline dense no-caps"
        ).classes(helpers.UI_STYLES.get_widget_style("query_chip")["classes"]).style(
            helpers.UI_STYLES.get_widget_style("query_chip")["style"]
        )

    # ========================================================================
    # Query Functions
    # ========================================================================

    def create_query_dialog(
        title: str, input_type: str, options: list = None, on_confirm=None
    ) -> None:
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

    async def save_custom_query() -> None:
        query = editor.value
        if not await _validate_query_syntax(query):
            return

        async def perform_save(popup, name: str):
            if not _validate_query_name(name, check_exists=True):
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

    async def update_custom_query() -> None:
        custom_queries = _get_custom_queries()
        if not custom_queries:
            ui.notify("No custom query exists", type="warning")
            LOG.warning("No custom query exists to update!")
            return
        query = editor.value
        if not await _validate_query_syntax(query):
            return

        async def perform_update(popup, name: str):
            if not _validate_query_name(name):
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

    async def delete_custom_query() -> None:
        custom_queries = _get_custom_queries()
        if not custom_queries:
            ui.notify("No custom query exists to delete", type="warning")
            return

        async def perform_delete(popup, name: str):
            if not _validate_query_name(name):
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

    async def execute_query() -> None:
        query = editor.value
        if not query.strip():
            return
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

                # Check edit mode state
                is_edit_mode = edit_mode_enabled.value

                column_defs = [
                    {
                        "field": unique_cols[i],
                        "headerName": str(col).lower(),
                        "editable": is_edit_mode,
                        "sortable": True,
                        "filter": True,
                    }
                    for i, col in enumerate(df.columns)
                ]
                grid_box.options["columnDefs"] = column_defs

                grid_box.options["enableRangeSelection"] = True
                grid_box.options["enableClipboard"] = True
                grid_box.options["suppressRowClickSelection"] = True
                grid_box.options["suppressCopyRowsToClipboard"] = True

                df.columns = unique_cols
                row_data = df.to_dict(orient="records")
                grid_box.options["rowData"] = row_data
                grid_box.update()

                # Auto-size columns to fit viewport - use run_method for proper context
                try:
                    grid_box.run_method("sizeColumnsToFit")
                except Exception:
                    pass  # Silently fail if method not available
            else:
                # Detect what kind of statement was run for a meaningful message
                first_word = query.strip().split()[0].upper()
                action_messages = {
                    "INSERT": "Row inserted successfully",
                    "UPDATE": "Row(s) updated successfully",
                    "DELETE": "Row(s) deleted successfully",
                    "CREATE": "Object created successfully",
                    "ALTER": "Object altered successfully",
                    "DROP": "Object dropped successfully",
                }
                msg = action_messages.get(first_word, "Query executed successfully")
                LOG.info(msg)
                ui.notify(msg, type="positive")

                # Clear the grid to avoid showing stale results
                grid_box.options["columnDefs"] = [
                    {"field": "info", "headerName": "Result"}
                ]
                grid_box.options["rowData"] = [{"info": msg}]
                grid_box.update()
        except Exception as e:
            error_msg = f"Query execution failed: {e}"
            LOG.error(error_msg)
            grid_box.options["columnDefs"] = [
                {"field": "error", "headerName": "❌ Error"}
            ]
            grid_box.options["rowData"] = [{"error": str(e)}]
            grid_box.update()

    def clear_query() -> None:
        editor.set_value("")
        try:
            grid_box.options["columnDefs"] = [{"field": ""}]
            grid_box.options["rowData"] = []
            grid_box.update()
        except Exception:
            pass

    # ========================================================================
    # Table Cell Editing
    # ========================================================================

    async def show_row_edit_popup(row_data) -> None:
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

        async def on_submit():
            required_fields = [
                f["name"] for f in fields if not f.get("optional", False)
            ]
            if not helpers.check_input(widgets, required_fields):
                return
            kwargs = {name: widget.value for name, widget in widgets.items()}
            kwargs["table_name"] = table_name
            kwargs["pk_data"] = pk_data
            try:
                if kwargs.get("git_id", None):
                    kwargs["git_id"] = int(kwargs["git_id"])
            except ValueError:  # Should never trigger!
                ui.notify("Git ID must be an integer", type="negative")
                LOG.warning("Invalid Git ID entered - must be an integer!")
                return

            try:
                await QE.function_db(save_data.function, **kwargs)
                msg_1, msg_2 = helpers.print_success(
                    table_name, save_data.main_param, save_data.main_action, widgets
                )
                LOG.info(msg_1)
                if msg_2:
                    LOG.info(msg_2)
                popup.close()
                core.event_bus.emit("ui_refresh_requested")
            except Exception as e:
                LOG.error(f"Error saving row: {e}")
                ui.notify(f"Error saving: {str(e)}", type="negative")

        save_data = SaveData(**action)
        widgets = {}
        dynamic_widgets = []
        parent_map = {}

        with ui.dialog() as popup:
            with ui.card().classes("rounded-lg").props("flat"):
                with entity_card_header():
                    ui.label(f"Edit {table_name.capitalize()}").classes(
                        helpers.UI_STYLES.get_widget_style(
                            "time_tracking_customer_name"
                        )["classes"]
                    ).style(
                        "overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:left;"
                    )
                    with ui.row().classes("gap-1 shrink-0"):
                        ui.button(icon="save", on_click=on_submit).props(
                            "color=primary"
                        )
                        ui.button(icon="close", on_click=popup.close).props(
                            "flat color=negative"
                        )

                ui.separator().classes(
                    helpers.UI_STYLES.get_layout_classes("divider_row")
                )

                with ui.column().classes("w-full gap-2 p-2"):

                    async def data_fetcher(source_key, parent_val=None):
                        if source_key not in data_sources:
                            return [] if parent_val is not None else ""
                        data = data_sources[source_key]
                        if parent_val and isinstance(data, dict):
                            return data.get(parent_val, [])
                        elif isinstance(data, list):
                            return data
                        elif isinstance(data, dict):
                            return data
                        return [] if parent_val is not None else ""

                    for field in fields:
                        field_type = field.get("type", "input")
                        field_name = field["name"]
                        parent_field = field.get("parent")
                        parent_widget = (
                            parent_map.get(parent_field) if parent_field else None
                        )

                        options_source = field.get("options_source")
                        if options_source and options_source not in data_sources:
                            data_sources[options_source] = table_row.get(options_source)
                        if field["name"] in table_row:
                            field["default"] = table_row.get(field["name"])

                        widget_class = WIDGET_CLASSES.get(field_type)
                        if not widget_class:
                            fallback_widgets, _ = helpers.make_input_row(
                                [field], defer_parent_wiring=True
                            )
                            widgets.update(fallback_widgets)
                            continue

                        widget_width = helpers.UI_STYLES.get_widget_width(
                            field.get("size", "standard")
                        )
                        dw = widget_class(
                            name=field_name,
                            data_fetcher=data_fetcher,
                            options_source=field.get("options_source", ""),
                            parent=parent_widget,
                            label=field.get("label", field_name),
                            initial_value=field.get("default"),
                            field_config=field,
                        )
                        dw.widget.classes(widget_width)
                        widgets[field_name] = dw
                        parent_map[field_name] = dw
                        dynamic_widgets.append(dw)

        popup.open()

    async def on_cell_clicked(event) -> None:
        if not edit_mode_enabled.value:
            return
        row_data = event.args["data"]
        await show_row_edit_popup(row_data)

    # ========================================================================
    # UI Rendering
    # ========================================================================
    def render_toolbar() -> Tuple[ui.row, ui.row]:
        """Render control panel - stable across data refreshes."""
        with toolbar(core.theme):
            with toolbar_group(core.theme, "Preset", divider_after=True):
                preset_queries = ui.row().classes("gap-2 flex-wrap")
            with toolbar_group(core.theme, "Custom", divider_after=False):
                custom_queries = ui.row().classes("gap-2 flex-wrap")
            ui.space()
            ui.button(icon="save", on_click=save_custom_query).props(
                "flat dense color=primary"
            ).tooltip("Save current query")
            ui.button(icon="edit", on_click=update_custom_query).props(
                "flat dense color=primary"
            ).tooltip("Update custom query")
            ui.button(icon="delete", on_click=delete_custom_query).props(
                "flat dense color=negative"
            ).tooltip("Delete custom query")

        return preset_queries, custom_queries

    def render_query_window() -> None:
        with page_card(scrollable=False):
            with ui.row().classes("w-full justify-between items-center"):
                ui.button(
                    "Execute Query (F5)",
                    icon="play_arrow",
                    on_click=execute_query,  # lambda: asyncio.create_task(execute_query()),
                ).props("color=primary size=sm")
                with ui.row().classes("items-center gap-4"):
                    ui.label("Edit Mode:").classes("text-sm " + helpers.UI_STYLES.get_layout_classes("muted_text"))
                    edit_mode_enabled = (
                        ui.switch(value=True)
                        .props("color=primary")
                        .tooltip(
                            "When ON: Click cells to edit data. Base tables are editable (time, customers, projects) and only select columns. Additional columns can be edited via the data-input tab. When OFF: Ctrl/Shift+Click rows to select, Ctrl+C to copy"
                        )
                    )

            initial_query = app.storage.user.get("query_editor_query", "")
            if not initial_query:
                try:
                    initial_query = QE.df[QE.df["query_name"] == "time"][
                        "query_sql"
                    ].values[0]
                except Exception:
                    initial_query = "select * from time order by time_id desc limit 100"

            editor = ui.codemirror(
                initial_query, language="SQLite", theme="dracula"
            ).classes("h-48 w-full")
            editor.bind_value(app.storage.user, "query_editor_query")

            grid_box = (
                ui.aggrid(
                    {
                        "columnDefs": [{"field": ""}],
                        "rowData": [],
                        "defaultColDef": {
                            "editable": False,
                            "sortable": True,
                            "filter": True,
                            "resizable": True,
                        },
                        "rowSelection": "multiple",
                        "suppressRowClickSelection": False,
                        "enableCellTextSelection": True,
                        "copyHeadersToClipboard": True,
                    },
                    theme="alpine-dark",
                )
                .classes("flex-1 w-full")
                .on("cellClicked", on_cell_clicked)
            )

            def on_edit_mode_change():
                is_edit = edit_mode_enabled.value
                grid_box.options["defaultColDef"]["editable"] = is_edit
                grid_box.options["suppressRowClickSelection"] = is_edit
                grid_box.update()

            edit_mode_enabled.on("update:model-value", lambda _: on_edit_mode_change())

            render_query_buttons()
            asyncio.create_task(refresh_query_list())

        return edit_mode_enabled, editor, grid_box

    preset_queries, custom_queries = render_toolbar()
    edit_mode_enabled, editor, grid_box = render_query_window()

    # Prevent F5 from refreshing the page using JavaScript
    ui.run_javascript("""
        document.addEventListener('keydown', function(e) {
            if (e.key === 'F5' || (e.ctrlKey && e.key === 'r')) {
                e.preventDefault();
            }
        });
    """)

    ui.run_javascript("""
        // Prevent text selection on grid when not in edit mode
        const style = document.createElement('style');
        style.id = 'ag-no-select';
        style.textContent = '.ag-root-wrapper * { user-select: none; !important; }';
        document.head.appendChild(style);
        
        document.addEventListener('keydown', function(e) {
            if (e.ctrlKey && e.key === 'c') {
                const selectedRows = Array.from(document.querySelectorAll('.ag-row-selected'));
                if (!selectedRows.length) return;
                
                e.preventDefault();  // stop browser default copy
                e.stopPropagation();
                
                selectedRows.sort((a, b) => {
                    const aTop = parseInt(a.style.transform?.match(/translateY\\((\\d+)px\\)/)?.[1] || 0);
                    const bTop = parseInt(b.style.transform?.match(/translateY\\((\\d+)px\\)/)?.[1] || 0);
                    return aTop - bTop;
                });
                
                const lines = selectedRows.map(row => {
                    const cells = Array.from(row.querySelectorAll('.ag-cell[col-id]'));
                    return cells.map(cell => cell.textContent.replace(/\\s+/g, ' ').trim()).join('\\t');
                });
                
                navigator.clipboard.writeText(lines.join('\\n'));
            }
        }, true);  // true = capture phase, fires before browser default
    """)

    def handle_key(e: KeyEventArguments):
        if e.key.f5 and e.action.keydown:
            ui.timer(0.0, execute_query, once=True)
        elif e.modifiers.ctrl and e.key.enter and e.action.keydown:
            ui.timer(0.0, execute_query, once=True)

    ui.keyboard(on_key=handle_key)

    # Execute initial query to populate grid
    ui.timer(0.1, execute_query, once=True)  #    asyncio.create_task(execute_query())
