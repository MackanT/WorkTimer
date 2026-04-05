"""
Add Data Page

Data input interface for creating new customers, projects, tasks, bonuses, and DevOps work items.
Uses V2 architecture with per-client AppCore and event-driven updates.
Fully config-driven using config_ui.yml structure.
"""

from datetime import date
from nicegui import ui
from ..core.app import AppCore
from .. import helpers
from ..ui.devops_handlers import DevOpsWorkItemHandlers
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
        "render_devops_tabs": render_devops_tabs,
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
                for page_dict in add_data_page_config:
                    p_data = add_data_page_config.get(page_dict, {}).get("meta", {})
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
                    except Exception as e:
                        core.logger.error(f"Error refreshing {tab_name}.{op}: {e}")

    main_tabs.on_value_change(on_tab_change)

    start_tab = next(iter(add_data_page_config))

    with (
        ui.tab_panels(main_tabs, value=start_tab)
        .props("vertical")
        .classes("w-full")
        .style(
            "background: transparent; height: calc(100vh - 156px); max-height: calc(100vh - 156px);"
        )
    ):
        for page_dict in add_data_page_config:
            p_data = add_data_page_config.get(page_dict, {}).get("meta", {})
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

    # Initialize storage for refresh functions if not exists
    if not hasattr(core, "_entity_refresh_fns"):
        core._entity_refresh_fns = {}
    if entity_type not in core._entity_refresh_fns:
        core._entity_refresh_fns[entity_type] = {}

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
    QE = core.query_engine
    LOG = core.logger

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
            await QE.function_db(action["function"], **kwargs)
            msg_1, msg_2 = helpers.print_success(
                entity_type,
                kwargs[action["main_param"]],
                action["secondary_action"],
                widgets,
            )
            LOG.info(msg_1)
            if msg_2:
                LOG.info(msg_2)
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
            LOG.error(f"Error in {operation} {entity_type}: {e}")
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
                        LOG.warning(
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


async def render_devops_tabs(
    core: AppCore, entity_type: str, operations: list, page_config: dict
):
    devops_config = page_config.get(entity_type, {})

    if not hasattr(core, "_entity_refresh_fns"):
        core._entity_refresh_fns = {}
    core._entity_refresh_fns.setdefault(entity_type, {})

    refresh_fns = []  # collect per-form refresh callables

    with (
        ui.tabs()
        .props("inline-label align=left scrollable dense")
        .classes("w-full") as sub_tabs
    ):
        ui.tab("add", label="Add")
        ui.tab("update", label="Update")

    with (
        ui.tab_panels(sub_tabs, value="add")
        .classes("w-full p-0")
        .style("background: transparent;")
    ):
        with ui.tab_panel("add").classes("p-0"):
            fn = await render_devops_form(core, "add", devops_config.get("add", {}))
            if fn:
                refresh_fns.append(fn)

        with ui.tab_panel("update").classes("p-0"):
            fn = await render_devops_form(core, "update", devops_config.get("update", {}))
            if fn:
                refresh_fns.append(fn)

    async def _refresh_devops():
        for fn in refresh_fns:
            await fn()

    core._entity_refresh_fns[entity_type]["devops"] = _refresh_devops


async def render_devops_form(core: AppCore, operation: str, form_config: dict):
    """Render DevOps work item form (shared by add and update)."""
    LOG = core.logger
    DO = core.devops_engine

    fields = form_config.get("fields", [])
    action = form_config.get("action", {})

    data_sources = await prepare_devops_data_sources(core, operation)
    helpers.assign_dynamic_options(fields, data_sources=data_sources)

    # Defined at function scope so both on_submit and refresh_all_widgets close over them
    widgets: dict = {}
    dynamic_widgets: list = []
    parent_map: dict = {}

    async def on_submit():
        required_fields = [
            f.get("name") or f.get("field_id")
            for f in fields
            if not f.get("optional", False)
        ]
        if not helpers.check_input(widgets, required_fields):
            return

        if not DO or not hasattr(DO, "manager") or not DO.manager:
            ui.notify("DevOps not configured – check PAT token / org URL", type="negative")
            return

        try:
            devops_handlers = DevOpsWorkItemHandlers(DO, LOG)
            if operation == "add":
                success, message = devops_handlers.add_work_item(widgets)
                if success:
                    wid_title = widgets.get("work_item_title")
                    ui.notify(f"Work item created: {wid_title.value if wid_title else ''}", type="positive")
                    LOG.info(message)
                    await DO.update_devops(incremental=True)
                    core.event_bus.emit("ui_refresh_requested")
                else:
                    ui.notify(f"Failed: {message}", type="negative")
                    LOG.error(message)
            else:
                success, message = await devops_handlers.update_work_item(widgets)
                if success:
                    ui.notify("Work item updated", type="positive")
                    LOG.info(message)
                    await DO.update_devops(incremental=True)
                    core.event_bus.emit("ui_refresh_requested")
                else:
                    ui.notify(f"Failed: {message}", type="negative")
                    LOG.error(message)
        except Exception as e:
            LOG.error(f"Error in DevOps {operation}: {e}")
            ui.notify(f"Error: {e}", type="negative")

    with (
        ui.card()
        .classes("overflow-y-auto w-full rounded-lg")
        .style("max-height: calc(100vh - 180px); padding: 1rem; box-sizing: border-box;")
        .props("flat")
    ):
        title = action.get("title", f"{operation.capitalize()} DevOps Work Item")
        with ui.row().classes("w-full items-center gap-2 mt-4"):
            ui.label(title).classes(helpers.UI_STYLES.get_layout_classes("title"))
            ui.space()
            ui.button(action.get("button_name", "Submit"), icon="save", on_click=on_submit).props("color=primary")

        if not data_sources.get("customer_data"):
            ui.label("No DevOps data available. Please configure DevOps connections first.").classes("text-warning")
            return None

        # Normalize: no explicit rows_layout → each field is its own single-element row.
        # This collapses the if/else into one code path with no behavioral difference.
        rows_layout = form_config.get("rows", []) or [
            [f.get("name") or f.get("field_id")] for f in fields
        ]

        async def devops_data_fetcher(source_key, parent_val=None):
            if source_key == "devops_tags":
                return core.devops_tags_config.devops_tags or []
            if source_key not in data_sources:
                return [] if parent_val is not None else ""
            data = data_sources[source_key]
            if source_key == "parent_names" and isinstance(data, dict) and parent_val:
                customer_dict = data.get(parent_val, {})
                if isinstance(customer_dict, dict):
                    all_parents = []
                    for parent_list in customer_dict.values():
                        if isinstance(parent_list, list):
                            all_parents.extend(parent_list)
                    return list(set(all_parents))
                return customer_dict if isinstance(customer_dict, list) else []
            if parent_val and isinstance(data, dict):
                return data.get(parent_val, [])
            elif isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data
            return [] if parent_val is not None else ""

        has_wide_layout = any(
            helpers.UI_STYLES.is_wide_widget(
                next((f.get("type") for f in fields if f.get("name") == fn or f.get("field_id") == fn), None)
            )
            for row in rows_layout
            for fn in row
        )

        with ui.column().classes(helpers.UI_STYLES.get_layout_classes("form_column")):
            for row in rows_layout:
                row_field_configs = [
                    fc
                    for fn in row
                    if (fc := next((f for f in fields if f.get("name") == fn or f.get("field_id") == fn), None))
                ]
                if not row_field_configs:
                    continue

                is_single_field = len(row_field_configs) == 1
                default_size = "full" if (has_wide_layout or is_single_field) else "standard"

                with ui.row().classes(helpers.UI_STYLES.get_layout_classes("form_row")):
                    for field in row_field_configs:
                        field_name = field.get("name") or field.get("field_id")
                        field_type = field.get("type", "input")
                        parent_field = field.get("parent")

                        widget_class = WIDGET_CLASSES.get(field_type)
                        if not widget_class:
                            LOG.warning(f"Unknown field type '{field_type}', skipping {field_name}")
                            continue

                        dw = widget_class(
                            name=field_name,
                            data_fetcher=devops_data_fetcher,
                            options_source=field.get("options_source", ""),
                            parent=parent_map.get(parent_field) if parent_field else None,
                            label=field.get("label", field_name),
                            initial_value=field.get("default"),
                            field_config=field,
                        )
                        dw.widget.classes(helpers.UI_STYLES.get_widget_width(field.get("size", default_size)))
                        widgets[field_name] = dw
                        parent_map[field_name] = dw
                        dynamic_widgets.append(dw)

        helpers.setup_template_handling(widgets)
        devops_handlers_setup = DevOpsWorkItemHandlers(DO, LOG)
        if operation == "add":
            devops_handlers_setup.setup_add_tab_handlers(widgets)
        else:
            devops_handlers_setup.setup_update_tab_handlers(widgets)

    async def refresh_all_widgets():
        try:
            for dw in dynamic_widgets:
                await dw.refresh()
        except Exception as e:
            core.logger.error(f"Error refreshing DevOps.{operation} widgets: {e}")

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
                # Get disabled customers
                df = await QE.query_db(
                    "SELECT DISTINCT customer_name FROM customers WHERE is_current = 0"
                )
                active_df = await QE.query_db(
                    "SELECT customer_name FROM customers WHERE is_current = 1"
                )
                active_names = set(
                    active_df["customer_name"].tolist() if not active_df.empty else []
                )
                all_disabled = set(df["customer_name"].tolist() if not df.empty else [])
                data_sources["customer_data"] = sorted(
                    list(all_disabled - active_names)
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
                            int(git_val)
                            if git_val is not None and git_val == git_val
                            else 0
                        )

            elif operation == "reenable":
                # Disabled projects grouped by customer (exclude any now-active ones)
                dis_df = await QE.query_db(
                    """SELECT DISTINCT p.project_name, c.customer_name
                       FROM projects p
                       JOIN customers c ON p.customer_id = c.customer_id
                       WHERE p.is_current = 0"""
                )
                active_df2 = await QE.query_db(
                    "SELECT project_name FROM projects WHERE is_current = 1"
                )
                active_proj = set(
                    active_df2["project_name"].tolist() if not active_df2.empty else []
                )
                project_names_by_cust = {}
                for _, row in (dis_df if not dis_df.empty else dis_df).iterrows():
                    pname = row["project_name"]
                    if pname in active_proj:
                        continue
                    project_names_by_cust.setdefault(row["customer_name"], []).append(
                        pname
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


async def prepare_devops_data_sources(core: AppCore, operation: str) -> dict:
    """Prepare data sources for DevOps forms"""
    DO = core.devops_engine
    data_sources = {}

    try:
        data_sources["devops_tags"] = core.devops_tags_config.devops_tags or []

        if not DO or not hasattr(DO, "df") or DO.df is None or DO.df.empty:
            return data_sources

        # Get customer names from DevOps data
        customer_names = DO.df["customer_name"].unique().tolist()
        data_sources["customer_data"] = customer_names

        # Prepare work items and parent relationships per customer
        work_items = {}
        parent_names = {}

        for customer in customer_names:
            customer_df = DO.df[DO.df["customer_name"] == customer]
            work_items[customer] = customer_df["display_name"].tolist()

            # Parent relationships
            epics = customer_df[customer_df["type"] == "Epic"]["display_name"].tolist()
            features = customer_df[customer_df["type"].isin(["Epic", "Feature"])][
                "display_name"
            ].tolist()

            parent_names[customer] = {
                "Epic": [],
                "Feature": epics,
                "User Story": features,
            }

        data_sources["work_items"] = work_items
        data_sources["parent_names"] = parent_names

        # Load DevOps contacts config if available
        try:
            config_devops = core.config_loader.get_raw_dict("devops_contacts")

            contact_persons = {}
            assignees = {}
            default_assignee = {}

            for customer in customer_names:
                customer_data = config_devops.get("customers", {}).get(customer, {})
                default_data = config_devops.get("default", {})

                contact_persons[customer] = customer_data.get(
                    "contacts", default_data.get("contacts", [])
                )
                assignees[customer] = customer_data.get(
                    "assignees", default_data.get("assignees", [])
                )
                default_assignee[customer] = customer_data.get("default_assignee", None)

            data_sources["contact_persons"] = contact_persons
            data_sources["assignees"] = assignees
            data_sources["default_assignee"] = default_assignee

        except Exception:
            pass  # DevOps contacts config is optional

    except Exception as e:
        core.logger.error(f"Error preparing DevOps data sources: {e}")

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
    import os
    import tempfile
    from nicegui import events

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
                .style("max-height: calc(100vh - 200px); overflow-y: auto;")
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
                .style("max-height: calc(100vh - 200px); overflow-y: auto;")
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

                uploaded_db_path = {"path": None}

                def handle_db_upload(e: events.UploadEventArguments):
                    ui.notify(f"Database uploaded: {e.name}", color="positive")
                    try:
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".db"
                        ) as tmp:
                            tmp.write(e.content.read())
                            uploaded_db_path["path"] = tmp.name
                        core.logger.info(
                            f"Database uploaded to: {uploaded_db_path['path']}"
                        )
                    except Exception as ex:
                        core.logger.error(f"Error uploading database: {ex}")
                        ui.notify(f"Error: {ex}", type="negative")

                async def execute_query():
                    if not uploaded_db_path["path"]:
                        ui.notify("Please upload a database first", type="warning")
                        return

                    query = query_editor.value
                    if not query:
                        ui.notify("Please enter a query", type="warning")
                        return

                    try:
                        import sqlite3
                        import pandas as pd

                        conn = sqlite3.connect(uploaded_db_path["path"])

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

                        conn.close()
                        core.logger.info("Query executed successfully")
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
