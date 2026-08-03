"""
Shared DevOps form rendering for board dialogs.

This module decouples DevOps add/update UI from add_data page so the
board can own the full DevOps workflow.
"""

import asyncio
import copy

from nicegui import ui

from .. import helpers
from ..ui.dynamic_widgets import WIDGET_CLASSES
from ..ui.devops_handlers import DevOpsWorkItemHandlers


_DIALOG_CARD_STYLE = (
    "margin: 2rem auto; width: calc(100% - 4rem); max-width: 980px;"
    "max-height: calc(100vh - 4rem); overflow-y: auto;"
)
_PRIORITY_COLORS = {1: "red-5", 2: "orange-4", 3: "blue-4", 4: "grey-4"}
_PRIORITY_LABELS = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}


async def open_work_item_dialog(
    core,
    row: dict,
    on_success=None,
    priority_colors: dict | None = None,
    priority_labels: dict | None = None,
):
    """Open the full DevOps work-item update dialog for a single item.

    Shared by the board (card click) and the hierarchy (node click). Shows the
    editable fields, the description and the comments thread, plus an
    "Open in DevOps" link. `on_success` (async, optional) runs after a save.
    """
    priority_colors = priority_colors or _PRIORITY_COLORS
    priority_labels = priority_labels or _PRIORITY_LABELS

    item_id = int(row.get("id", 0))
    item_type = str(row.get("type", "User Story"))
    title = str(row.get("title", ""))
    customer = str(row.get("customer_name", ""))
    priority_val = row.get("priority")
    display_name = f"{item_type}: {item_id} - {title}"
    update_cfg = core.ui_config.get("board_devops_forms", {}).get("update", {})

    def _open_in_devops():
        manager = getattr(core.devops_engine, "manager", None)
        url = manager.get_work_item_url(customer, item_id) if manager else None
        if url:
            ui.navigate.to(url, new_tab=True)
        else:
            ui.notify("Could not build the Azure DevOps URL", type="warning")

    with ui.dialog().props("maximized") as dlg:
        with ui.card().style(_DIALOG_CARD_STYLE).props("flat bordered"):
            form_actions: dict = {"submit": None}
            dirty_state: dict = {"is_dirty": False, "programmatic": True}

            def _mark_dirty(_e=None):
                if not dirty_state["programmatic"]:
                    dirty_state["is_dirty"] = True

            def _confirm_discard_or_close():
                if not dirty_state["is_dirty"]:
                    dlg.close()
                    return
                with ui.dialog() as confirm_dlg, ui.card().classes("w-96"):
                    ui.label("Discard unsaved changes?").classes("text-sm font-semibold")
                    ui.label("Your edits in this work item will be lost.").classes(
                        "text-xs text-grey-5"
                    )
                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                        ui.button("Keep editing", on_click=confirm_dlg.close).props("flat")

                        def _discard():
                            confirm_dlg.close()
                            dlg.close()

                        ui.button("Discard", on_click=_discard).props("color=negative")
                confirm_dlg.open()

            async def _submit_from_header():
                submit_fn = form_actions.get("submit")
                if submit_fn:
                    await submit_fn()

            # ── header ────────────────────────────────────────────────────────
            p_color = priority_colors.get(priority_val, "grey-4")
            p_label = priority_labels.get(priority_val, "")
            with ui.row().classes("items-center gap-2 no-wrap w-full").style(
                "padding: 0.6rem 0.8rem; flex-shrink: 0;"
            ):
                if priority_val:
                    ui.icon("circle", size="12px").classes(
                        f"text-{p_color} shrink-0"
                    ).tooltip(f"Priority: {p_label}")
                ui.label(f"#{item_id}").classes("text-grey-5 text-xs shrink-0")
                ui.label("·").classes("text-grey-5 text-xs shrink-0")
                ui.label(item_type).classes("text-grey-5 text-xs shrink-0")
                ui.label(title).classes("text-sm font-semibold flex-1").style(
                    "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                )
                ui.badge(customer).props("color=primary outline rounded").classes("text-xs shrink-0")
                ui.space()
                ui.button(icon="open_in_new", on_click=_open_in_devops).props(
                    "flat dense color=primary"
                ).tooltip("Open in Azure DevOps")
                ui.button("Update", icon="save", on_click=_submit_from_header).props("dense color=primary")
                ui.button("Cancel", icon="close", on_click=_confirm_discard_or_close).props(
                    "flat dense color=grey-6"
                )
            ui.separator()

            loading_box = ui.column().classes("w-full gap-2").style("padding: 0.75rem;")
            with loading_box:
                ui.skeleton("text", width="35%")
                for _ in range(3):
                    ui.skeleton("rect", width="100%", height="52px")
                ui.skeleton("rect", width="100%", height="220px")

            dlg.open()
            await asyncio.sleep(0)

            async def _on_update_success():
                dlg.close()
                if on_success:
                    await on_success()

            result = await render_devops_form(
                core, "update", update_cfg,
                on_success=_on_update_success,
                hidden_field_names={"customer_name", "work_item", "current_column", "board_column"},
                show_internal_header=False,
            )

            _, widgets, load_fn, submit_fn = result if result else (None, {}, None, None)
            form_actions["submit"] = submit_fn

            if widgets:
                if "customer_name" in widgets:
                    widgets["customer_name"].widget.value = customer
                    widgets["customer_name"].widget.update()
                if "work_item" in widgets:
                    await widgets["work_item"].refresh()
                    widgets["work_item"].widget.value = display_name
                    widgets["work_item"].widget.update()
                if load_fn:
                    await load_fn(None)

                dirty_state["programmatic"] = False
                for field_name in ("state", "assigned_to", "priority", "description_editor"):
                    w = widgets.get(field_name)
                    if w:
                        w.on_value_change(_mark_dirty)

            loading_box.clear()


def _render_comment(comment: dict) -> None:
    """Render one Azure DevOps comment (author/date header + body)."""
    with ui.card().props("flat bordered").classes("w-full"):
        ui.label(
            f"{comment.get('author') or 'Unknown'} · {str(comment.get('date') or '')[:16].replace('T', ' ')}"
        ).classes("text-xs text-grey-5")
        text = comment.get("text") or ""
        # ADO comments are usually HTML; render as sanitized markdown either way.
        md = helpers.convert_html_to_markdown(text) if "<" in text else text
        ui.html(helpers.render_and_sanitize_markdown(md)).classes("text-sm w-full")


async def _load_comments_into(core, widgets: dict, container) -> None:
    """Fetch the selected work item's comments and render them into `container`."""
    wid_widget = widgets.get("work_item")
    cust_widget = widgets.get("customer_name")
    container.clear()
    if not wid_widget or not cust_widget:
        return
    work_item_id = helpers.extract_devops_id(wid_widget.value)
    customer = cust_widget.value
    if not work_item_id or not customer:
        return
    manager = getattr(core.devops_engine, "manager", None)
    if not manager:
        return

    with container:
        ui.label("Loading comments…").classes("text-xs text-grey-5")
    ok, data = await asyncio.to_thread(manager.get_comments, customer, work_item_id)
    container.clear()
    with container:
        if not ok:
            ui.label(f"Could not load comments: {data}").classes("text-xs text-negative")
        elif not data:
            ui.label("No comments yet.").classes("text-xs text-grey-5")
        else:
            for comment in data:
                _render_comment(comment)


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
    # Deep-copy: the config dicts are shared process-wide; assign_dynamic_options
    # writes options into the field dicts, which must not leak across clients.
    fields = copy.deepcopy(form_config.get("fields", []))
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
                success, message = await devops_handlers.add_work_item(widgets)
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
        _setup_conditional_visibility(widgets, fields_by_name, hidden)
        devops_handlers_setup = DevOpsWorkItemHandlers(core.devops_engine, core.logger)
        if operation == "add":
            load_fn = devops_handlers_setup.setup_add_tab_handlers(widgets)
        else:
            load_fn = devops_handlers_setup.setup_update_tab_handlers(widgets)

        # Comments panel (update only) — the work item's discussion thread, read
        # only. Shown in the board dialog and the hierarchy dialog alike.
        if operation == "update":
            ui.separator().classes("mt-3")
            ui.label("Comments").classes(
                helpers.UI_STYLES.get_layout_classes("muted_text_xs") + " mt-2"
            )
            comments_box = ui.column().classes("w-full gap-2")

            async def _reload_comments(_e=None):
                await _load_comments_into(core, widgets, comments_box)

            work_item_widget = widgets.get("work_item")
            if work_item_widget:
                work_item_widget.on("update:model-value", _reload_comments)

            # Fold comment-loading into load_fn so callers that prefill the work
            # item (the board/hierarchy dialogs) load comments too.
            _inner_load = load_fn

            async def load_fn(_e=None, _base=_inner_load):
                if _base:
                    await _base(_e)
                await _reload_comments(_e)

    async def refresh_all_widgets():
        try:
            for dw in dynamic_widgets:
                await dw.refresh()
        except Exception as e:
            core.logger.error(f"Error refreshing DevOps.{operation} widgets: {e}")

    return refresh_all_widgets, widgets, load_fn, on_submit


def _setup_conditional_visibility(widgets: dict, fields_by_name: dict, hidden: set) -> None:
    """Wire `conditional: true` / `visible_when:` field configs to widget visibility.

    Restores a feature the legacy form factory used to provide: e.g. the DevOps
    add form hides Source/Contact/Parent unless the work item type matches.
    Bound via on_value_change, which also fires on programmatic value sets
    (e.g. the board dialog pre-selecting the work item type).
    """
    conditional = [
        (name, cfg.get("visible_when"))
        for name, cfg in fields_by_name.items()
        if cfg.get("conditional") and cfg.get("visible_when")
        and name in widgets and name not in hidden
    ]
    if not conditional:
        return

    def apply_visibility(_e=None):
        for name, visible_when in conditional:
            visible = True
            for cond_field, cond_values in visible_when.items():
                cond_widget = widgets.get(cond_field)
                value = cond_widget.value if cond_widget is not None else None
                if not value:
                    visible = False
                    break
                if isinstance(cond_values, list):
                    if value not in cond_values:
                        visible = False
                        break
                elif value != cond_values:
                    visible = False
                    break
            widgets[name].widget.set_visibility(visible)

    condition_fields = {cf for _, vw in conditional for cf in vw}
    for cond_field in condition_fields:
        if cond_field in widgets:
            widgets[cond_field].on_value_change(apply_visibility)

    apply_visibility()


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
