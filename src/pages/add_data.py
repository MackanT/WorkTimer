"""
Add Data Page

Data input interface for creating new customers, projects, tasks, bonuses, and DevOps work items.
Uses V2 architecture with per-client AppCore and event-driven updates.
Fully config-driven using config_ui.yml structure.
"""

import os
import sqlite3
import tempfile
import pandas as pd
from datetime import date
from nicegui import ui, events
from ..core.app import AppCore
from .. import helpers
from ..ui.dynamic_widgets import WIDGET_CLASSES
from ..ui.elements import (
    toolbar,
    entity_card_shell,
    entity_card_header,
    entity_card_content,
)


async def add_data_page():
    """Add Data page - for creating new entities

    Note: No @ui.page decorator - accessed via SPA sub_pages in root.py
    Direct access to /add_data is handled by redirect in root.py
    """

    core = await AppCore.get_or_initialize()

    add_data_page_config = core.ui_config.get("add_data_page", {})

    BUILD_FUNCTIONS = {
        "render_entity_tabs": render_entity_tabs,
        "render_database_tabs": render_database_tabs,
    }

    # ========================================================================
    # Toolbar Controls
    # ========================================================================
    def render_toolbar():
        """Render control panel - stable across data refreshes."""
        with toolbar(core.theme):
            with (
                ui.tabs(value="customer")
                .props(
                    f'horizontal dense active-color="{core.theme.get("accent")}" indicator-color="{core.theme.get("accent")}"'
                )
                .classes(helpers.UI_STYLES.get_layout_classes("tab_label"))
            ) as main_tabs:
                for page_dict, page_section in add_data_page_config.items():
                    p_data = page_section.get("meta", {})
                    icon = p_data.get("icon", "warning")
                    label = p_data.get("friendly_name", page_dict)
                    ui.tab(page_dict, label=label, icon=icon)

        return main_tabs

    main_tabs = render_toolbar()

    # Wire up tab change to trigger refresh
    async def on_tab_change(e):
        tab_name = e.value
        # Refresh all forms in the newly visible tab
        if (
            hasattr(core, "_entity_refresh_fns")
            and tab_name in core._entity_refresh_fns
        ):
            for op, refresh_fn in core._entity_refresh_fns[tab_name].items():
                if refresh_fn:
                    try:
                        await refresh_fn()
                        core.logger.debug(f"Refreshed {tab_name}.{op} on tab change")
                    except Exception as err:
                        core.logger.error(f"Error refreshing {tab_name}.{op}: {err}")

    main_tabs.on_value_change(on_tab_change)

    start_tab = next(iter(add_data_page_config))

    with (
        ui.tab_panels(main_tabs, value=start_tab)
        .props("vertical")
        .classes("wt-page-content w-full")
        .style(
            "background: transparent;"
        )
    ):
        for page_dict, page_section in add_data_page_config.items():
            p_data = page_section.get("meta", {})
            build_fn_name = p_data.get("build_function")

            with ui.tab_panel(page_dict):
                if build_fn_name and build_fn_name in BUILD_FUNCTIONS:
                    build_fn = BUILD_FUNCTIONS[build_fn_name]
                    await build_fn(
                        core,
                        page_dict,
                        p_data.get("options", []),
                        add_data_page_config,
                    )
                else:
                    core.logger.warning(
                        f"No build function '{build_fn_name}' found for {page_dict}"
                    )
                    ui.label("Configuration error: build function not found").classes(
                        "text-warning"
                    )


async def render_entity_tabs(
    core: AppCore, entity_type: str, operations: list, page_config: dict
):
    """Render sub-tabs for entity operations (Add/Update/Disable/Reenable)"""
    entity_config = page_config.get(entity_type, {})

    # Initialize storage for refresh functions
    if not hasattr(core, "_entity_refresh_fns"):
        core._entity_refresh_fns = {}
    core._entity_refresh_fns.setdefault(entity_type, {})

    with ui.row(wrap=False):
        for op in operations:
            refresh_fn = await render_entity_form(
                core=core,
                entity_type=entity_type,
                operation=op,
                form_config=entity_config.get(op, {}),
            )
            core._entity_refresh_fns[entity_type][op] = refresh_fn


async def render_entity_form(
    core: AppCore, entity_type: str, operation: str, form_config: dict
):
    """Render a single entity form based on config"""
    fields = form_config.get("fields", [])
    action = form_config.get("action", {})

    data_sources = await prepare_data_sources(core, entity_type, operation)
    helpers.assign_dynamic_options(fields, data_sources=data_sources)

    widgets = {}
    dynamic_widgets = []
    parent_map = {}

    async def on_submit():  ## TODO somewhere here detect if DevOps was updated and trigger re-init if so (could also be done via event bus) core.force_devops_reinit()
        required_fields = [f["name"] for f in fields if not f.get("optional", False)]
        if not helpers.check_input(widgets, required_fields):
            return
        kwargs = {name: widget.value for name, widget in widgets.items()}
        try:
            await core.query_engine.function_db(action["function"], **kwargs)
            msg_1, msg_2 = helpers.print_success(
                entity_type,
                kwargs[action["main_param"]],
                action["secondary_action"],
                widgets,
            )
            core.logger.info(msg_1)
            if msg_2:
                core.logger.info(msg_2)
            for widget in widgets.values():
                if hasattr(widget, "value"):
                    widget.value = "" if isinstance(widget.value, str) else None
            if (
                hasattr(core, "_entity_refresh_fns")
                and entity_type in core._entity_refresh_fns
            ):
                core.logger.debug(f"Refreshing all {entity_type} tabs")
                for op, refresh_fn in core._entity_refresh_fns[entity_type].items():
                    if refresh_fn:
                        try:
                            await refresh_fn()
                            core.logger.debug(f"Refreshed {entity_type}.{op}")
                        except Exception as e:
                            core.logger.error(
                                f"Error refreshing {entity_type}.{op}: {e}"
                            )
            core.event_bus.emit("ui_refresh_requested")
        except Exception as e:
            core.logger.error(f"Error in {operation} {entity_type}: {e}")
            ui.notify(f"Error: {e}", type="negative")

    with entity_card_shell():
        with entity_card_header():
            with ui.element("div").style(
                "display:flex; align-items:center; gap:0.25rem; overflow:hidden;"
            ):
                ui.label(operation.capitalize()).classes(
                    helpers.UI_STYLES.get_widget_style("time_tracking_customer_name")[
                        "classes"
                    ]
                ).style(
                    "overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:left;"
                )
                ui.space()
                ui.button(icon="save", on_click=on_submit).props("color=primary")

        ui.separator().classes(
            helpers.UI_STYLES.get_layout_classes("divider_row")
        )

        with entity_card_content():

            async def data_fetcher(source_key, parent_val=None):
                fresh = await prepare_data_sources(core, entity_type, operation)
                if source_key not in fresh:
                    return [] if parent_val is not None else ""
                data = fresh[source_key]
                if parent_val and isinstance(data, dict):
                    return data.get(parent_val, [])
                elif isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data
                return [] if parent_val is not None else ""

            with ui.column().classes("w-full gap-2"):
                for field in fields:
                    field_type = field.get("type", "input")
                    field_name = field["name"]
                    parent_field = field.get("parent")
                    parent_widget = (
                        parent_map.get(parent_field) if parent_field else None
                    )

                    widget_class = WIDGET_CLASSES.get(field_type)
                    if not widget_class:
                        core.logger.warning(
                            f"Unknown field type '{field_type}', using fallback"
                        )
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

    async def refresh_all_widgets():
        try:
            for dw in dynamic_widgets:
                await dw.refresh()
        except Exception as e:
            core.logger.error(f"Error refreshing {entity_type}.{operation} widgets: {e}")

    return refresh_all_widgets


async def prepare_data_sources(core: AppCore, entity_type: str, operation: str) -> dict:
    """Prepare data sources for entity forms"""
    QE = core.query_engine
    data_sources = {}

    try:
        if entity_type == "customer":
            if operation in ["update", "disable"]:
                # Get active customers
                df = await QE.query_db(
                    "SELECT customer_name FROM customers WHERE is_current = 1"
                )
                data_sources["customer_data"] = (
                    df["customer_name"].tolist() if not df.empty else []
                )

                if operation == "update":
                    # For update, we need current values per customer
                    full_df = await QE.query_db(
                        "SELECT customer_name, org_url, pat_token FROM customers WHERE is_current = 1"
                    )
                    data_sources["org_url"] = {}
                    data_sources["pat_token"] = {}
                    data_sources["new_customer_name"] = {}
                    for _, row in full_df.iterrows():
                        cname = row["customer_name"]
                        data_sources["org_url"][cname] = row["org_url"] or ""
                        data_sources["pat_token"][cname] = row["pat_token"] or ""
                        data_sources["new_customer_name"][cname] = cname

            elif operation == "reenable":
                # Get customers that are disabled and have no active entry
                df = await QE.query_db(
                    """SELECT DISTINCT customer_name FROM customers
                       WHERE is_current = 0
                       AND customer_name NOT IN (
                           SELECT customer_name FROM customers WHERE is_current = 1
                       )"""
                )
                data_sources["customer_data"] = sorted(
                    df["customer_name"].tolist() if not df.empty else []
                )

            # Today's date for start_date
            data_sources["today"] = date.today().isoformat()

        elif entity_type == "project":
            # Get active customers
            df = await QE.query_db(
                "SELECT customer_id, customer_name FROM customers WHERE is_current = 1"
            )
            data_sources["customer_data"] = (
                df["customer_name"].tolist() if not df.empty else []
            )

            if operation in ["update", "disable"]:
                # Get active projects grouped by customer (for parent-dependent dropdown)
                grouped_df = await QE.query_db(
                    """SELECT p.project_name, c.customer_name
                       FROM projects p
                       JOIN customers c ON p.customer_id = c.customer_id
                       WHERE p.is_current = 1"""
                )
                project_names_by_cust: dict = {}
                for _, row in grouped_df.iterrows():
                    project_names_by_cust.setdefault(row["customer_name"], []).append(
                        row["project_name"]
                    )
                data_sources["project_names"] = project_names_by_cust
                # Keep flat list for backward compat
                data_sources["project_data"] = [
                    p for lst in project_names_by_cust.values() for p in lst
                ]

                if operation == "update":
                    # Get project details per project for auto-population
                    full_df = await QE.query_db(
                        """SELECT p.project_name, p.git_id
                           FROM projects p
                           WHERE p.is_current = 1"""
                    )
                    data_sources["new_project_name"] = {}
                    data_sources["new_git_id"] = {}
                    for _, row in full_df.iterrows():
                        pname = row["project_name"]
                        # Plain strings/numbers so _update_input_field sets correct values
                        data_sources["new_project_name"][pname] = pname
                        git_val = row["git_id"]
                        data_sources["new_git_id"][pname] = (
                            int(git_val) if pd.notna(git_val) else 0
                        )

            elif operation == "reenable":
                # Disabled projects grouped by customer (excluding any now-active ones)
                dis_df = await QE.query_db(
                    """SELECT DISTINCT p.project_name, c.customer_name
                       FROM projects p
                       JOIN customers c ON p.customer_id = c.customer_id
                       WHERE p.is_current = 0
                       AND p.project_name NOT IN (
                           SELECT project_name FROM projects WHERE is_current = 1
                       )"""
                )
                project_names_by_cust = {}
                for _, row in dis_df.iterrows():
                    project_names_by_cust.setdefault(row["customer_name"], []).append(
                        row["project_name"]
                    )
                data_sources["project_names"] = project_names_by_cust
                data_sources["project_data"] = [
                    p for lst in project_names_by_cust.values() for p in lst
                ]

            data_sources["today"] = date.today().isoformat()

        elif entity_type == "bonus":
            # Get active customers and projects
            cust_df = await QE.query_db(
                "SELECT customer_name FROM customers WHERE is_current = 1"
            )
            proj_df = await QE.query_db(
                "SELECT project_name FROM projects WHERE is_current = 1"
            )
            data_sources["customer_data"] = (
                cust_df["customer_name"].tolist() if not cust_df.empty else []
            )
            data_sources["project_data"] = (
                proj_df["project_name"].tolist() if not proj_df.empty else []
            )
            data_sources["today"] = date.today().isoformat()

    except Exception as e:
        core.logger.error(
            f"Error preparing data sources for {entity_type}.{operation}: {e}"
        )

    return data_sources




async def render_database_tabs(
    core: AppCore, entity_type: str, operations: list, page_config: dict
):
    """Render database management tabs (Compare and Update)

    Args:
        core: AppCore instance
        entity_type: Entity type (unused, for signature compatibility)
        operations: List of operations (unused, for signature compatibility)
        page_config: Page configuration dict (unused, for signature compatibility)
    """
    from ..database import Database

    # Get database name from settings
    db_name = core.settings.db_path

    with (
        ui.tabs()
        .props("inline-label align=left")
        .classes(helpers.UI_STYLES.get_layout_classes("full_width")) as db_tabs
    ):
        ui.tab("compare", label="Compare")
        ui.tab("update", label="Update")

    with ui.tab_panels(db_tabs, value="compare").classes(
        helpers.UI_STYLES.get_layout_classes("full_width")
    ):
        # Compare tab
        with ui.tab_panel("compare"):
            with (
                ui.card()
                .classes(
                    helpers.UI_STYLES.get_card_classes("xs", "card").replace(
                        "mx-auto", "ml-0"
                    )
                )
                .style("max-height: 82vh; overflow-y: auto;")
            ):
                ui.label(
                    "Upload a .db file to compare with the main database."
                ).classes(helpers.UI_STYLES.get_layout_classes("title"))

                db_deltas = ui.codemirror("", language="SQL", theme="dracula").classes(
                    "w-full h-96"
                )

                def handle_upload(e: events.UploadEventArguments):
                    ui.notify(f"File uploaded: {e.name}", color="positive")
                    try:
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".db"
                        ) as tmp:
                            tmp.write(e.content.read())
                            uploaded_path = tmp.name

                        sync_sql = Database.generate_sync_sql(db_name, uploaded_path)
                        db_deltas.set_content(sync_sql)
                        os.remove(uploaded_path)  # Clean up temp file
                    except Exception as ex:
                        core.logger.error(f"Error comparing databases: {ex}")
                        ui.notify(f"Error: {ex}", type="negative")

                ui.upload(on_upload=handle_upload).props("accept=.db").classes(
                    "q-pa-xs q-ma-xs"
                )

        # Update tab
        with ui.tab_panel("update"):
            with (
                ui.card()
                .classes(
                    helpers.UI_STYLES.get_card_classes("xs", "card").replace(
                        "mx-auto", "ml-0"
                    )
                )
                .style("max-height: 82vh; overflow-y: auto;")
            ):
                ui.label("Run SQL queries on uploaded database").classes(
                    helpers.UI_STYLES.get_layout_classes("title")
                )

                query_editor = ui.codemirror(
                    "", language="SQL", theme="dracula"
                ).classes("w-full h-48")

                result_display = ui.codemirror(
                    "", language="text", theme="dracula"
                ).classes("w-full h-96")

                uploaded_db_path = None

                def handle_db_upload(e: events.UploadEventArguments):
                    nonlocal uploaded_db_path
                    ui.notify(f"Database uploaded: {e.name}", color="positive")
                    try:
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".db"
                        ) as tmp:
                            tmp.write(e.content.read())
                            uploaded_db_path = tmp.name
                        core.logger.info(
                            f"Database uploaded to: {uploaded_db_path}"
                        )
                    except Exception as ex:
                        core.logger.error(f"Error uploading database: {ex}")
                        ui.notify(f"Error: {ex}", type="negative")

                async def execute_query():
                    if not uploaded_db_path:
                        ui.notify("Please upload a database first", type="warning")
                        return

                    query = query_editor.value
                    if not query:
                        ui.notify("Please enter a query", type="warning")
                        return

                    try:
                        conn = sqlite3.connect(uploaded_db_path)
                        try:
                            if query.strip().upper().startswith("SELECT"):
                                # Read query - show results
                                df = pd.read_sql_query(query, conn)
                                result_display.set_content(df.to_string())
                                ui.notify(f"Query returned {len(df)} rows", type="positive")
                            else:
                                # Write query - execute and show rows affected
                                cursor = conn.cursor()
                                cursor.execute(query)
                                conn.commit()
                                rows_affected = cursor.rowcount
                                result_display.set_content(
                                    f"Query executed successfully. Rows affected: {rows_affected}"
                                )
                                ui.notify(
                                    f"Query executed. {rows_affected} rows affected",
                                    type="positive",
                                )
                            core.logger.info("Query executed successfully")
                        finally:
                            conn.close()
                    except Exception as ex:
                        core.logger.error(f"Error executing query: {ex}")
                        result_display.set_content(f"Error: {ex}")
                        ui.notify(f"Error: {ex}", type="negative")

                ui.upload(on_upload=handle_db_upload).props("accept=.db").classes(
                    "q-pa-xs q-ma-xs"
                )

                with ui.row().classes("gap-2 mt-2"):
                    ui.button(
                        "Execute Query", icon="play_arrow", on_click=execute_query
                    ).props("color=primary")
