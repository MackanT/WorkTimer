"""
Shared DevOps form rendering for board dialogs.

This module decouples DevOps add/update UI from add_data page so the
board can own the full DevOps workflow.
"""

from nicegui import ui

from .. import helpers
from ..ui.dynamic_widgets import WIDGET_CLASSES
from ..ui.devops_handlers import DevOpsWorkItemHandlers


async def render_devops_form(
    core,
    operation: str,
    form_config: dict,
    on_success=None,
    on_close=None,
    hidden_field_names: set = None,
    show_internal_header: bool = True,
):
    """Render DevOps work item form (shared by add and update)."""
    fields = form_config.get("fields", [])
    action = form_config.get("action", {})

    data_sources = await prepare_devops_data_sources(core, operation)
    helpers.assign_dynamic_options(fields, data_sources=data_sources)

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

        if (
            not core.devops_engine
            or not hasattr(core.devops_engine, "manager")
            or not core.devops_engine.manager
        ):
            ui.notify("DevOps not configured - check PAT token / org URL", type="negative")
            return

        try:
            devops_handlers = DevOpsWorkItemHandlers(core.devops_engine, core.logger)
            if operation == "add":
                wid_title = widgets.get("work_item_title")
                success, message = devops_handlers.add_work_item(widgets)
                success_msg = f"Work item created: {wid_title.value if wid_title else ''}"
            else:
                success, message = await devops_handlers.update_work_item(widgets)
                success_msg = "Work item updated"

            if success:
                ui.notify(success_msg, type="positive")
                core.logger.info(message)
                await core.devops_engine.update_devops(incremental=True)
                core.event_bus.emit("ui_refresh_requested")
                if on_success:
                    await on_success()
            else:
                ui.notify(f"Failed: {message}", type="negative")
                core.logger.error(message)
        except Exception as e:
            core.logger.error(f"Error in DevOps {operation}: {e}")
            ui.notify(f"Error: {e}", type="negative")

    with (
        ui.card()
        .classes("overflow-y-auto w-full rounded-lg")
        .style("max-height: 82vh; padding: 1rem; box-sizing: border-box;")
        .props("flat")
    ):
        if show_internal_header:
            title = action.get("title", f"{operation.capitalize()} DevOps Work Item")
            with ui.row().classes("w-full items-center gap-2 mt-4"):
                ui.label(title).classes(helpers.UI_STYLES.get_layout_classes("title"))
                ui.space()
                ui.button(action.get("button_name", "Submit"), icon="save", on_click=on_submit).props("color=primary")
                if on_close:
                    ui.button(icon="close", on_click=on_close).props("flat dense round color=grey-6").tooltip("Close")

        if not data_sources.get("customer_data"):
            ui.label("No DevOps data available. Please configure DevOps connections first.").classes("text-warning")
            return None, {}, None, None

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
                    return list({
                        item
                        for parent_list in customer_dict.values()
                        if isinstance(parent_list, list)
                        for item in parent_list
                    })
                return customer_dict if isinstance(customer_dict, list) else []
            if parent_val and isinstance(data, dict):
                return data.get(parent_val, [])
            elif isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data
            return [] if parent_val is not None else ""

        field_name_to_type = {f.get("name") or f.get("field_id"): f.get("type") for f in fields}
        fields_by_name = {f.get("name") or f.get("field_id"): f for f in fields}
        hidden = set(hidden_field_names or [])
        has_wide_layout = any(
            helpers.UI_STYLES.is_wide_widget(field_name_to_type.get(fn))
            for row in rows_layout
            for fn in row
        )

        if hidden:
            with ui.element("div").style("display: none;"):
                for field in fields:
                    fname = field.get("name") or field.get("field_id")
                    if fname not in hidden or fname in widgets:
                        continue
                    widget_class = WIDGET_CLASSES.get(field.get("type", "input"))
                    if not widget_class:
                        continue
                    parent_field = field.get("parent")
                    dw = widget_class(
                        name=fname,
                        data_fetcher=devops_data_fetcher,
                        options_source=field.get("options_source", ""),
                        parent=parent_map.get(parent_field) if parent_field else None,
                        label=field.get("label", fname),
                        initial_value=field.get("default"),
                        field_config=field,
                    )
                    widgets[fname] = dw
                    parent_map[fname] = dw
                    dynamic_widgets.append(dw)

        with ui.column().classes(helpers.UI_STYLES.get_layout_classes("form_column")):
            for row in rows_layout:
                row_field_configs = [fields_by_name[fn] for fn in row if fn in fields_by_name and fn not in hidden]
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
                            core.logger.warning(f"Unknown field type '{field_type}', skipping {field_name}")
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
        devops_handlers_setup = DevOpsWorkItemHandlers(core.devops_engine, core.logger)
        load_fn = None
        if operation == "add":
            devops_handlers_setup.setup_add_tab_handlers(widgets)
        else:
            load_fn = devops_handlers_setup.setup_update_tab_handlers(widgets)

    async def refresh_all_widgets():
        try:
            for dw in dynamic_widgets:
                await dw.refresh()
        except Exception as e:
            core.logger.error(f"Error refreshing DevOps.{operation} widgets: {e}")

    return refresh_all_widgets, widgets, load_fn, on_submit


async def prepare_devops_data_sources(core, operation: str) -> dict:
    """Prepare data sources for DevOps forms."""
    DO = core.devops_engine
    data_sources = {}

    try:
        data_sources["devops_tags"] = core.devops_tags_config.devops_tags or []

        if not DO or not hasattr(DO, "df") or DO.df is None or DO.df.empty:
            return data_sources

        customer_names = DO.df["customer_name"].unique().tolist()
        data_sources["customer_data"] = customer_names

        work_items = {}
        parent_names = {}

        for customer in customer_names:
            customer_df = DO.df[DO.df["customer_name"] == customer]
            work_items[customer] = customer_df["display_name"].tolist()

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

        except Exception as e:
            core.logger.debug(f"DevOps contacts config not available: {e}")

    except Exception as e:
        core.logger.error(f"Error preparing DevOps data sources: {e}")

    return data_sources
