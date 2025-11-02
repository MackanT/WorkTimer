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
    config_query = GlobalRegistry.get("config_query") if GlobalRegistry.get("config_query") else {}
    
    # Get UI_STYLES from helpers
    UI_STYLES = helpers.UI_STYLES
    
    asyncio.run(QE.refresh())

    async def save_custom_query():
        query = editor.value
        try:
            await QE.query_db(query)
        except Exception:
            ui.notify("Query is invalid", color="negative")
            LOG.log_msg("WARNING", "Custom query is invalid and cannot be saved!")
            return

        def close_popup():
            popup.close()

        async def save_popup():
            name = name_input.value.strip()
            if not name:
                ui.notify("Query name required", color="negative")
                LOG.log_msg(
                    "WARNING", "Custom query name is required and cannot be saved!"
                )
                return
            if name in QE.df["query_name"].tolist():
                ui.notify("Query name already exists", color="negative")
                LOG.log_msg(
                    "WARNING", "Custom query name already exists and cannot be saved!"
                )
                return
            await QE.function_db(
                "execute_query",
                "insert into queries (query_name, query_sql) values (?, ?)",
                (name, query),
            )
            ui.notify(f"Query '{name}' saved!", color="positive")
            LOG.log_msg("INFO", f"Custom query '{name}' saved successfully!")
            popup.close()
            await QE.refresh()
            render_query_buttons()

        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("standard")):
                name_input = ui.input("Query Name").classes("w-full")
                with ui.row().classes("justify-between items-center w-full"):
                    ui.button("Save", on_click=save_popup).classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
                    ui.button("Cancel", on_click=close_popup).props("flat").classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
        popup.open()

    async def update_custom_query():
        if len(QE.df[QE.df["is_default"] != 1]["query_name"]) == 0:
            ui.notify("No custom query exists", color="negative")
            LOG.log_msg("WARNING", "No custom query exists to update!")
            return

        query = editor.value
        try:
            await QE.query_db(query)
        except Exception:
            ui.notify("Query is invalid", color="negative")
            LOG.log_msg("WARNING", "Custom query is invalid and cannot be updated!")
            return

        def close_popup():
            popup.close()

        async def save_popup():
            name = name_input.value.strip()
            if not name:
                ui.notify("Select an existing query", color="negative")
                LOG.log_msg("WARNING", "No query name selected for update!")
                return
            await QE.function_db(
                "execute_query",
                "update queries set query_sql = ? where query_name = ?",
                (query, name),
            )
            ui.notify(f"Query '{name}' updated!", color="positive")
            LOG.log_msg("INFO", f"Custom query '{name}' updated successfully!")
            popup.close()
            await QE.refresh()
            render_query_buttons()

        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("standard")):
                name_input = ui.select(
                    options=QE.df[QE.df["is_default"] != 1]["query_name"].tolist(),
                    label="Existing Query",
                ).classes("w-full")
                with ui.row().classes("justify-between items-center w-full"):
                    ui.button("Update", on_click=save_popup).classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
                    ui.button("Cancel", on_click=close_popup).props("flat").classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
        popup.open()

    async def delete_custom_query():
        if len(QE.df[QE.df["is_default"] != 1]["query_name"]) == 0:
            ui.notify("At least one custom query must exist", color="negative")
            return

        def close_popup():
            popup.close()

        async def save_popup():
            name = name_input.value.strip()
            if not name:
                ui.notify("Select an existing query", color="negative")
                LOG.log_msg("WARNING", "No query name selected for deletion!")
                return
            await QE.function_db(
                "execute_query",
                "delete from queries where query_name = ?",
                (name,),
            )
            ui.notify(f"Query '{name}' deleted!", color="positive")
            LOG.log_msg("INFO", f"Custom query '{name}' deleted successfully!")
            popup.close()
            await QE.refresh()
            render_query_buttons()

        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("standard")):
                name_input = ui.select(
                    options=QE.df[QE.df["is_default"] != 1]["query_name"].tolist(),
                    label="Existing Query",
                ).classes("w-full")
                with ui.row().classes("justify-between items-center w-full"):
                    ui.button("Delete", on_click=save_popup).classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
                    ui.button("Cancel", on_click=close_popup).props("flat").classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
        popup.open()

    def add_save_button(save_data, fields, widgets, table_name, pk_data, popup):
        async def on_save():
            required_fields = [
                f["name"] for f in fields if not f.get("optional", False)
            ]
            if not helpers.check_input(widgets, required_fields):
                return
            kwargs = {f["name"]: widgets[f["name"]].value for f in fields}
            # Convert any single-item list in kwargs to a string
            for k, v in kwargs.items():
                if isinstance(v, list):
                    if len(v) == 1:
                        kwargs[k] = v[0]
                    elif len(v) > 1:  ## TODO make nicer
                        raise ValueError(
                            f"Field '{k}' has multiple values: {v}. Only one value is allowed."
                        )

            kwargs["table_name"] = table_name
            kwargs["pk_data"] = pk_data

            await QE.function_db(save_data.function, **kwargs)

            val = (
                ""
                if save_data.main_param == "None"
                else widgets[save_data.main_param].value
            )
            sec_action = (
                ""
                if save_data.secondary_action == "None"
                else save_data.secondary_action
            )
            msg_1, msg_2 = helpers.print_success(
                save_data.main_action,
                val,
                sec_action,
                widgets=widgets,
            )
            LOG.log_msg("INFO", msg_1)
            LOG.log_msg("INFO", msg_2)
            close_popup()

        def close_popup():
            popup.close()

        with ui.row().classes("justify-end gap-2"):
            ui.button(save_data.button_name, on_click=on_save).classes(
                UI_STYLES.get_layout_classes("button_fixed")
            )
            ui.button("Cancel", on_click=close_popup).props("flat").classes(
                UI_STYLES.get_layout_classes("button_fixed")
            )

    with ui.row().classes("justify-between items-center w-full"):
        preset_queries = ui.element()

        def render_query_buttons_group(queries):
            for _, row in queries.iterrows():
                ui.button(
                    row["query_name"],
                    on_click=lambda r=row: editor.set_value(r["query_sql"]),
                ).props("flat dense").classes(
                    UI_STYLES.get_widget_style("query_button", "base")["classes"]
                )

        def render_query_buttons():
            preset_queries.clear()
            with preset_queries:
                with ui.button_group().classes("gap-1"):
                    render_query_buttons_group(QE.df[QE.df["is_default"] == 1])
                    ui.separator().props("vertical").classes("mx-2")
                    render_query_buttons_group(QE.df[QE.df["is_default"] != 1])

        render_query_buttons()

        with ui.button_group().classes("gap-1"):
            for name, function in [
                ("Save Query", save_custom_query),
                ("Update Query", update_custom_query),
                ("Delete Query", delete_custom_query),
            ]:
                ui.button(
                    name,
                    on_click=function,
                ).props("flat dense").classes(
                    UI_STYLES.get_widget_style("query_button", "base")["classes"]
                )

    async def show_row_edit_popup(row_data):
        table_name = helpers.extract_table_name(editor.value)

        if table_name not in ["time", "customers", "projects"]:
            ui.notify(f"Table {table_name} is not registered for editing!")
            return

        base_name = table_name[:-1] if table_name.endswith("s") else table_name
        key_col = f"{base_name}_id"

        if key_col not in row_data:
            ui.notify(
                f"Cannot find {table_name}'s primary key: {key_col} in your query!",
                color="negative",
            )
            return

        pk_data = (key_col, row_data[key_col])

        table_row = await QE.function_db("get_query_edit_data", table_name, pk_data[1])
        table_row = (
            table_row.iloc[0] if not table_row.empty else {}
        )  ## TODO return with error
        projects = await QE.query_db(
            f"select project_name from projects where customer_id = {table_row.get('customer_id', 0)} and is_current = 1"
        )

        fields = config_query["query"][table_name]["fields"]
        action = config_query["query"][table_name]["action"]

        data_sources = {}
        for field in fields:
            # Special handling for project_names in time table
            if table_name == "time":
                data_sources["project_names"] = projects["project_name"].tolist()
                data_sources["default_project"] = table_row.get("project_name", None)

            options_source = field.get("options_source")
            if options_source:
                data_sources[options_source] = table_row.get(options_source, None)

        helpers.assign_dynamic_options(
            fields,
            data_sources=data_sources,
        )

        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("medium")):
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets, table_name, pk_data, popup)
            popup.open()

    async def on_cell_clicked(event):
        row_data = event.args["data"]
        await show_row_edit_popup(row_data)

    ui.label("Query Editors")

    initial_query = QE.df[QE.df["query_name"] == "time"]["query_sql"].values[0]
    editor = ui.codemirror(
        initial_query,
        language="SQLite",
        theme="dracula",
    ).classes("h-48 w-full")
    grid_box = (
        ui.aggrid(
            {
                "columnDefs": [{"field": ""}],
                "rowData": [],
            },
            theme="alpine-dark",
        )
        .classes("h-96 w-full")
        .on(
            "cellClicked",
            on_cell_clicked,
        )
    )

    async def run_code():
        query = editor.value
        try:
            df = await QE.query_db(query)
            if df is not None:
                grid_box.options["columnDefs"] = [
                    {"field": str(col).lower(), "headerName": str(col).lower()}
                    for col in df.columns
                ]
                grid_box.options["rowData"] = df.to_dict(orient="records")
                grid_box.update()
            else:
                with grid_box:
                    ui.notify("Query executed successfully (no result set).")
        except Exception as e:
            with grid_box:
                ui.notify(f"Error: {e}")

    asyncio.run(run_code())

    def handle_key(e: KeyEventArguments):
        if e.key.f5 and not e.key.shift and e.action.keydown:  # Check for F5 key press
            asyncio.create_task(run_code())

    ui.keyboard(on_key=handle_key)
