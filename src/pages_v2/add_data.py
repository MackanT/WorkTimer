"""
Add Data Page (V2)

Data input interface for creating new customers, projects, tasks, bonuses, and DevOps work items.
Uses V2 architecture with per-client AppCore and event-driven updates.
Fully config-driven using config_ui.yml structure.
"""

from datetime import date
from nicegui import ui
from ..core.app import AppCore, get_config_loader
from .. import helpers
from ..ui.navigation import create_navigation
from ..ui.devops_handlers import DevOpsWorkItemHandlers


@ui.page("/add_data")
async def add_data_page():
    """Add Data page - for creating new entities"""

    # Get or create AppCore for this client
    config_loader = get_config_loader()
    core = AppCore.get_or_create(config_loader)

    # Enable dark mode
    dark = ui.dark_mode()
    dark.enable()

    # Navigation
    create_navigation()

    # Initialize engines if needed
    if not core._initialized:
        await core.initialize_engines()

    # Shortcuts
    config_ui = core.config_loader.get_raw_dict("ui")

    # Main content: splitter fills remaining viewport height below nav bar
    with ui.splitter(value=20).classes("add-data-splitter") as splitter:
        # Left side: Vertical tabs
        with splitter.before:
            with (
                ui.tabs()
                .props("vertical")
                .classes(
                    helpers.UI_STYLES.get_layout_classes("full_width")
                ) as main_tabs
            ):
                # Get icons from config
                customer_icon = (
                    config_ui.get("customer", {}).get("meta", {}).get("icon", "person")
                )
                project_icon = (
                    config_ui.get("project", {}).get("meta", {}).get("icon", "work")
                )
                bonus_icon = (
                    config_ui.get("bonus", {})
                    .get("meta", {})
                    .get("icon", "card_giftcard")
                )
                devops_icon = (
                    config_ui.get("devops_work_item", {})
                    .get("meta", {})
                    .get("icon", "cloud")
                )

                ui.tab("customer", label="Customer", icon=customer_icon)
                ui.tab("project", label="Project", icon=project_icon)
                ui.tab("devops", label="DevOps", icon=devops_icon)
                ui.tab("bonus", label="Bonus", icon=bonus_icon)
                ui.tab("database", label="Database", icon="storage")

        # Right side: Tab content
        with splitter.after:
            with (
                ui.tab_panels(main_tabs, value="customer")
                .props("vertical")
                .classes("w-full h-full overflow-y-auto")
            ):
                # Customer tab
                with ui.tab_panel("customer"):
                    await render_entity_tabs(
                        core, "customer", ["add", "update", "disable", "reenable"]
                    )

                # Project tab
                with ui.tab_panel("project"):
                    await render_entity_tabs(
                        core, "project", ["add", "update", "disable", "reenable"]
                    )

                # DevOps tab
                with ui.tab_panel("devops"):
                    await render_devops_tabs(core)

                # Bonus tab
                with ui.tab_panel("bonus"):
                    await render_entity_tabs(core, "bonus", ["add"])

                # Database tab
                # with ui.tab_panel("database"):
                #     await render_database_tabs(core)

    ui.timer(
        0.0,
        lambda: ui.run_javascript("""
        (function(){
            function fit() {
                var nav = document.querySelector('.worktimer-navigation');
                var sp  = document.querySelector('.add-data-splitter');
                if (!nav || !sp) return;
                var top = nav.getBoundingClientRect().bottom;
                sp.style.setProperty('position', 'fixed', 'important');
                sp.style.setProperty('top', top + 'px', 'important');
                sp.style.setProperty('left', '0', 'important');
                sp.style.setProperty('width', '100vw', 'important');
                sp.style.setProperty('height', (window.innerHeight - top) + 'px', 'important');
                sp.style.setProperty('overflow', 'hidden', 'important');
                sp.style.setProperty('z-index', '10', 'important');
            }
            fit();
            // Replace resize handler on each page render (handles re-navigation)
            if (window._addDataResizeHandler) {
                window.removeEventListener('resize', window._addDataResizeHandler);
            }
            window._addDataResizeHandler = function() { fit(); };
            window.addEventListener('resize', window._addDataResizeHandler);
        })();
        """),
        once=True,
    )


async def render_entity_tabs(core: AppCore, entity_type: str, operations: list):
    """Render sub-tabs for entity operations (Add/Update/Disable/Reenable)"""
    config_ui = core.config_loader.get_raw_dict("ui")
    entity_config = config_ui.get(entity_type, {})

    with (
        ui.tabs()
        .props("inline-label align=left scrollable dense")
        .classes("w-full") as sub_tabs
    ):
        for op in operations:
            op_label = op.capitalize()
            ui.tab(op, label=op_label)

    refresh_fns: dict = {}
    with ui.tab_panels(sub_tabs, value=operations[0]).classes("w-full"):
        for op in operations:
            with ui.tab_panel(op):
                refresh_fn = await render_entity_form(
                    core, entity_type, op, entity_config.get(op, {})
                )
                refresh_fns[op] = refresh_fn

    async def on_tab_change(e):
        val = e.args if not isinstance(e.args, dict) else e.args.get("value", "")
        fn = refresh_fns.get(str(val))
        if fn:
            await fn()

    sub_tabs.on("update:model-value", on_tab_change)


async def render_entity_form(
    core: AppCore, entity_type: str, operation: str, form_config: dict
):
    """Render a single entity form based on config"""
    QE = core.query_engine
    LOG = core.logger

    fields = form_config.get("fields", [])
    action = form_config.get("action", {})

    # Prepare data sources
    data_sources = await prepare_data_sources(core, entity_type, operation)

    # Assign dynamic options to fields
    helpers.assign_dynamic_options(fields, data_sources=data_sources)

    # Create form
    with (
        ui.card()
        .classes("w-fit ml-0 my-0 p-4")
        .style("max-height: calc(100vh - 200px); overflow-y: auto;")
    ):
        ui.label(f"{operation.capitalize()} {entity_type.capitalize()}").classes(
            helpers.UI_STYLES.get_layout_classes("title")
        )

        widgets, pending_relations = helpers.make_input_row(
            fields, defer_parent_wiring=True
        )
        if pending_relations:
            helpers.bind_parent_relations(widgets, pending_relations, {}, data_sources)

        # Submit button
        async def on_submit():
            # Validate required fields
            required_fields = [
                f["name"] for f in fields if not f.get("optional", False)
            ]
            if not helpers.check_input(widgets, required_fields):
                return

            # Gather values
            kwargs = {name: widget.value for name, widget in widgets.items()}

            try:
                # Call database function
                await QE.function_db(action["function"], **kwargs)

                # Success message
                msg_1, msg_2 = helpers.print_success(
                    entity_type,
                    action["main_param"],
                    action["secondary_action"],
                    widgets,
                )
                LOG.info(msg_1)
                if msg_2:
                    LOG.info(msg_2)

                # Clear form values
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

                # Trigger UI refresh
                core.event_bus.emit("ui_refresh_requested")

            except Exception as e:
                LOG.error(f"Error in {operation} {entity_type}: {e}")
                ui.notify(f"Error: {e}", type="negative")

        with ui.row().classes("gap-2 mt-4"):
            ui.button(
                action.get("button_name", "Submit"), icon="save", on_click=on_submit
            ).props("color=primary")

    async def refresh_top_level_selects():
        fresh = await prepare_data_sources(core, entity_type, operation)
        for f in fields:
            if f.get("type") == "select" and not f.get("parent"):
                src = f.get("options_source")
                if src and src in fresh and isinstance(fresh[src], list):
                    w = widgets.get(f["name"])
                    if w and hasattr(w, "options"):
                        w.options = fresh[src]
                        w.update()

    return refresh_top_level_selects


async def render_devops_tabs(core: AppCore):
    """Render DevOps work item tabs"""
    config_ui = core.config_loader.get_raw_dict("ui")
    devops_config = config_ui.get("devops_work_item", {})

    with (
        ui.tabs()
        .props("inline-label align=left scrollable dense")
        .classes("w-full") as sub_tabs
    ):
        ui.tab("add", label="Add")
        ui.tab("update", label="Update")

    with ui.tab_panels(sub_tabs, value="add").classes("w-full"):
        with ui.tab_panel("add"):
            await render_devops_form(core, "add", devops_config.get("add", {}))

        with ui.tab_panel("update"):
            await render_devops_form(core, "update", devops_config.get("update", {}))


async def render_devops_form(core: AppCore, operation: str, form_config: dict):
    """Render DevOps work item form"""
    LOG = core.logger
    DO = core.devops_engine

    fields = form_config.get("fields", [])
    action = form_config.get("action", {})

    # Prepare DevOps-specific data
    data_sources = await prepare_devops_data_sources(core, operation)

    # Assign dynamic options to field configs
    helpers.assign_dynamic_options(fields, data_sources=data_sources)

    render_functions = {"render_and_sanitize": helpers.render_and_sanitize_markdown}

    # Use a full-width card so the editor + preview can sit side by side
    with (
        ui.card()
        .classes(
            helpers.UI_STYLES.get_card_classes("full", "card").replace(
                "mx-auto", "ml-0"
            )
            + " overflow-y-auto"
        )
        .style(
            "width: 100%; min-width: 0; box-sizing: border-box; max-height: calc(100vh - 180px);"
        )
    ):
        ui.label(f"{operation.capitalize()} DevOps Work Item").classes(
            helpers.UI_STYLES.get_layout_classes("title")
        )

        if not data_sources.get("customer_data"):
            ui.label(
                "No DevOps data available. Please configure DevOps connections first."
            ).classes("text-warning")
            return

        rows_layout = form_config.get("rows", [])
        widgets: dict = {}
        pending_relations: list = []

        if rows_layout:
            has_wide_layout = any(
                helpers.UI_STYLES.is_wide_widget(
                    next(
                        (
                            f.get("type")
                            for f in fields
                            if f.get("name") == fn or f.get("field_id") == fn
                        ),
                        None,
                    )
                )
                for row in rows_layout
                for fn in row
            )

            with ui.column().classes(
                helpers.UI_STYLES.get_layout_classes("form_column")
            ):
                for row in rows_layout:
                    row_field_configs = [
                        fc
                        for fn in row
                        if (
                            fc := next(
                                (
                                    f
                                    for f in fields
                                    if f.get("name") == fn or f.get("field_id") == fn
                                ),
                                None,
                            )
                        )
                    ]

                    if not row_field_configs:
                        continue

                    is_single_field = len(row_field_configs) == 1
                    # Use "full" (w-full flex-1) when wide layout is active OR only one field
                    widget_size = (
                        "full" if (has_wide_layout or is_single_field) else None
                    )

                    with ui.row().classes(
                        helpers.UI_STYLES.get_layout_classes("form_row")
                    ):
                        _, rels = helpers.make_input_row(
                            row_field_configs,
                            layout_mode=widget_size,
                            widgets=widgets,
                            defer_parent_wiring=True,
                            render_functions=render_functions,
                        )
                        pending_relations.extend(rels)
        else:
            with ui.column():
                _, rels = helpers.make_input_row(
                    fields,
                    widgets=widgets,
                    defer_parent_wiring=True,
                    render_functions=render_functions,
                )
                pending_relations.extend(rels)

        if pending_relations:
            helpers.bind_parent_relations(
                widgets, pending_relations, render_functions, data_sources
            )

        devops_handlers_setup = DevOpsWorkItemHandlers(DO, LOG)
        if operation == "add":
            devops_handlers_setup.setup_add_tab_handlers(widgets)
        else:
            devops_handlers_setup.setup_update_tab_handlers(widgets)

        # ── Submit button ──────────────────────────────────────────────────────
        async def on_submit():
            required_fields = [
                f.get("name") or f.get("field_id")
                for f in fields
                if not f.get("optional", False)
            ]
            if not helpers.check_input(widgets, required_fields):
                return

            if not DO or not hasattr(DO, "manager") or not DO.manager:
                ui.notify(
                    "DevOps not configured – check PAT token / org URL", type="negative"
                )
                return

            try:
                devops_handlers = DevOpsWorkItemHandlers(DO, LOG)

                if operation == "add":
                    success, message = devops_handlers.add_work_item(widgets)
                    if success:
                        wid_title = widgets.get("work_item_title")
                        title_val = wid_title.value if wid_title else ""
                        ui.notify(f"Work item created: {title_val}", type="positive")
                        LOG.info(message)
                        await DO.update_devops(incremental=True)
                        core.event_bus.emit("ui_refresh_requested")
                    else:
                        ui.notify(f"Failed: {message}", type="negative")
                        LOG.error(message)

                else:  # update
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

        with ui.row().classes("gap-2 mt-4"):
            ui.button(
                action.get("button_name", "Submit"), icon="save", on_click=on_submit
            ).props("color=primary")


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
        data_sources["devops_tags"] = core.data_config.devops_tags or []

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


async def render_database_tabs(core: AppCore):
    """Render database management tabs (Compare and Update)"""
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
