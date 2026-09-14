"""
Entity management dialogs (formerly the Data Input page).

Customers, trackers, projects and bonuses are managed in dialogs that open
right over whatever page is showing — from the nav bar's Data menu or a
palette command — instead of a dedicated page. Fully config-driven from
config_ui.yml's add_data_page section (kept under its historical key).
"""

import asyncio
import copy
import pandas as pd
from datetime import date
from nicegui import ui
from ..core.app import AppCore
from .. import helpers
from ..ui.dynamic_widgets import WIDGET_CLASSES

_OP_TAB_LABELS = {"reenable": "Re-enable"}

# Field types that take the full form width in the two-column grid.
_WIDE_FIELD_TYPES = {"textarea", "editor_with_preview", "devops_id"}


def entity_sections(core) -> dict:
    """{entity_key: section} for the configured manageable entities —
    feeds the nav bar's Data menu and the palette's shortcuts."""
    return {
        name: sec
        for name, sec in (core.ui_config.get("add_data_page") or {}).items()
        if sec.get("meta", {}).get("build_function") == "render_entity_tabs"
    }


async def open_entity_dialog(
    core: AppCore,
    entity_type: str,
    operation: str = None,
    presets: dict = None,
):
    """Open the management dialog for one entity: operation tabs
    (Add/Update/…) on top, the active operation's form below in a two-column
    grid. `operation` preselects a tab; `presets` ({field_name: value})
    pre-fills fields of that tab (e.g. the customer for a project add) —
    focus goes to the first field that is NOT preset."""
    section = core.ui_config.get("add_data_page", {}).get(entity_type, {})
    meta = section.get("meta", {})
    operations = list(meta.get("options", []))
    if not operations:
        ui.notify(f"No forms configured for '{entity_type}'", type="warning")
        return None

    # Dialog-local registry: a submit refreshes the sibling operation forms,
    # and the preselected operation's first field gets keyboard focus.
    registry: dict = {"refresh": {}, "first": {}}

    accent = core.theme.get("accent")
    with ui.dialog() as dlg, ui.card().props("flat bordered").classes(
        "rounded-lg"
    ).style("width: min(860px, 95vw); max-width: 95vw; padding: 0;"):
        with ui.row().classes("items-center gap-2 no-wrap w-full").style(
            "padding: 0.6rem 0.8rem 0;"
        ):
            ui.icon(meta.get("icon", "input"), size="sm").classes(f"text-{accent}")
            ui.label(
                meta.get("friendly_name", entity_type.capitalize())
            ).classes("text-base font-semibold flex-1")
            ui.button(icon="close", on_click=dlg.close).props(
                "flat dense round color=grey-6"
            )
        with (
            ui.tabs()
            .props(
                f'dense align=center active-color="{accent}" '
                f'indicator-color="{accent}" no-caps'
            )
            .classes("w-full")
        ) as op_tabs:
            for op in operations:
                ui.tab(op, label=_OP_TAB_LABELS.get(op, op.capitalize()))
        ui.separator()
        with ui.tab_panels(
            op_tabs,
            value=operation if operation in operations else operations[0],
        ).classes("w-full").style("background: transparent;"):
            for op in operations:
                with ui.tab_panel(op).style("padding: 1rem;"):
                    registry["refresh"][op] = await render_entity_form(
                        core=core,
                        entity_type=entity_type,
                        operation=op,
                        form_config=section.get(op, {}),
                        registry=registry,
                    )

    registry["close"] = dlg.close  # a successful submit closes the dialog
    dlg.on("hide", lambda: dlg.delete())  # transient — never accumulates
    dlg.open()

    target_op = operation if operation in operations else operations[0]
    op_widgets = registry.get("widgets", {}).get(target_op, {})

    if presets:
        # Walk fields in FORM order (parents precede their children), and for
        # a parent-dependent preset field load its options BEFORE setting the
        # value — such a select starts empty, and a value outside the current
        # options doesn't stick (that lost the project preselect).
        for fname, dw in op_widgets.items():
            if fname not in presets:
                continue
            if getattr(dw, "parent", None) is not None:
                try:
                    await dw.refresh()
                except Exception:
                    pass
            try:
                dw.widget.value = presets[fname]
                dw.widget.update()
            except Exception:
                pass
        # Programmatic sets don't fire the browser event that reloads the
        # remaining dependent dropdowns — refresh them now.
        for fname, dw in op_widgets.items():
            if fname in presets:
                continue
            if getattr(dw, "parent", None) is not None:
                try:
                    await dw.refresh()
                except Exception:
                    pass

    focus_widget = registry["first"].get(target_op)
    if presets:
        for fname, dw in op_widgets.items():
            if fname not in presets:
                focus_widget = dw.widget
                break
    if focus_widget is not None:
        await asyncio.sleep(0.15)  # let the dialog render in the browser
        try:
            focus_widget.run_method("focus")
        except Exception:
            pass  # focus is a nicety
    return dlg


async def render_entity_form(
    core: AppCore,
    entity_type: str,
    operation: str,
    form_config: dict,
    registry: dict,
):
    """Render a single entity form based on config. `registry` is the host
    dialog's {"refresh": {op: fn}, "first": {op: widget}} shared state."""
    # Deep-copy: the config dicts are shared process-wide; assign_dynamic_options
    # writes options into the field dicts, which must not leak across clients.
    fields = copy.deepcopy(form_config.get("fields", []))
    action = form_config.get("action", {})

    data_sources = await prepare_data_sources(core, entity_type, operation)
    helpers.assign_dynamic_options(fields, data_sources=data_sources)

    widgets = {}
    dynamic_widgets = []
    parent_map = {}

    async def on_submit():
        required_fields = [f["name"] for f in fields if not f.get("optional", False)]
        if not helpers.check_input(widgets, required_fields):
            return
        kwargs = {name: widget.value for name, widget in widgets.items()}
        # Snapshot before the values get cleared below — used to decide whether
        # this change touched tracker connections (see re-init at the end).
        devops_touched = entity_type == "tracker" or (
            entity_type == "customer"
            and (
                operation in ("disable", "reenable")
                or bool(kwargs.get("tracker_name"))
                or bool(kwargs.get("devops_project"))
            )
        )
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
            # A successful submit closes the dialog (it self-deletes on hide,
            # so no field clearing / sibling refresh is needed).
            close_fn = registry.get("close")
            if close_fn:
                close_fn()
            core.event_bus.emit("ui_refresh_requested")

            # A customer's DevOps credentials (or active state) changed — rebuild
            # the DevOps engine so the board/work-item forms pick it up without an
            # app restart. force_devops_reinit() bypasses the retry cooldown and
            # re-inits in the background.
            if devops_touched:
                core.logger.info(
                    f"Tracker config changed ({entity_type}.{operation}) — "
                    "re-initializing tracker connections"
                )
                core.force_devops_reinit()
        except Exception as e:
            core.logger.error(f"Error in {operation} {entity_type}: {e}")
            ui.notify(f"Error: {e}", type="negative")

    # Per-cycle cache: without it, every child-widget refresh re-ran all
    # of prepare_data_sources' queries. refresh_all_widgets() invalidates
    # it once per cycle so data stays fresh after submits/tab changes.
    _sources_cache: dict = {"data": None}

    async def data_fetcher(source_key, parent_val=None):
        if _sources_cache["data"] is None:
            _sources_cache["data"] = await prepare_data_sources(
                core, entity_type, operation
            )
        fresh = _sources_cache["data"]
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

    with ui.column().classes("w-full gap-4"):
        # Two-column field grid — halves the form height and fills the card
        # instead of the old one-per-row stack. Wide types span both columns.
        with ui.grid(columns=2).classes("w-full gap-3"):
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
                        f"Unknown field type '{field_type}' for '{field_name}' — skipping"
                    )
                    continue

                dw = widget_class(
                    name=field_name,
                    data_fetcher=data_fetcher,
                    options_source=field.get("options_source", ""),
                    parent=parent_widget,
                    label=field.get("label", field_name),
                    initial_value=field.get("default"),
                    field_config=field,
                )
                dw.widget.classes("w-full")
                if field_type in _WIDE_FIELD_TYPES:
                    dw.widget.classes("col-span-2")
                widgets[field_name] = dw
                parent_map[field_name] = dw
                dynamic_widgets.append(dw)

        with ui.row().classes("w-full justify-end"):
            save_btn = ui.button(
                action.get("button_name", "Save"), icon="save"
            ).props("color=primary")

            async def _submit_with_spinner():
                save_btn.props("loading")
                try:
                    await on_submit()
                finally:
                    try:
                        save_btn.props(remove="loading")
                    except Exception:
                        pass

            save_btn.on("click", _submit_with_spinner)

    # Widgets (field order preserved) and first field per form — the dialog
    # uses these for presets and keyboard focus.
    registry.setdefault("widgets", {})[operation] = widgets
    registry.setdefault("first", {})[operation] = (
        dynamic_widgets[0].widget if dynamic_widgets else None
    )

    async def refresh_all_widgets():
        try:
            _sources_cache["data"] = None  # refetch once for this refresh cycle
            for dw in dynamic_widgets:
                await dw.refresh()
        except Exception as e:
            core.logger.error(f"Error refreshing {entity_type}.{operation} widgets: {e}")

    return refresh_all_widgets


def _devops_ids_by_customer(core: AppCore) -> dict:
    """{customer_name: [{"label", "id"}, …]} for the Git-ID picker; {} when
    DevOps isn't connected (the picker then falls back to manual id entry)."""
    eng = getattr(core, "devops_engine", None)
    return eng.get_work_item_options() if eng is not None else {}


async def prepare_data_sources(core: AppCore, entity_type: str, operation: str) -> dict:
    """Prepare data sources for entity forms"""
    QE = core.query_engine
    data_sources = {}

    try:
        if entity_type == "customer":
            # Trackers a customer can link to (credentials live on the
            # tracker entity, not the customer).
            tdf = await QE.query_db(
                "SELECT tracker_name FROM trackers ORDER BY tracker_name"
            )
            data_sources["tracker_data"] = (
                tdf["tracker_name"].tolist() if not tdf.empty else []
            )

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
                        "SELECT c.customer_name, c.devops_project, "
                        "c.expected_work_pct, c.billing_round_minutes, c.color, "
                        "t.tracker_name "
                        "FROM customers c "
                        "LEFT JOIN trackers t ON t.tracker_id = c.tracker_id "
                        "WHERE c.is_current = 1"
                    )
                    data_sources["new_customer_name"] = {}
                    data_sources["tracker_current"] = {}
                    # Current project per customer (preselects the picker).
                    data_sources["devops_project_current"] = {}
                    data_sources["expected_work_pct"] = {}
                    data_sources["billing_round_minutes"] = {}
                    data_sources["color"] = {}
                    for _, row in full_df.iterrows():
                        cname = row["customer_name"]
                        data_sources["new_customer_name"][cname] = cname
                        data_sources["tracker_current"][cname] = (
                            row["tracker_name"] or ""
                        )
                        data_sources["devops_project_current"][cname] = (
                            row["devops_project"] or ""
                        )
                        data_sources["expected_work_pct"][cname] = (
                            float(row["expected_work_pct"])
                            if pd.notna(row["expected_work_pct"]) else 0
                        )
                        data_sources["billing_round_minutes"][cname] = (
                            int(row["billing_round_minutes"])
                            if pd.notna(row["billing_round_minutes"]) else 0
                        )
                        data_sources["color"][cname] = row["color"] or ""
                    # Available projects per customer, from the live connections.
                    eng = getattr(core, "devops_engine", None)
                    data_sources["devops_projects"] = (
                        eng.get_available_projects() if eng is not None else {}
                    )

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

        elif entity_type == "tracker":
            # Registered tracker providers feed the "Type" selector — a new
            # provider module (e.g. Jira) appears here automatically.
            from ..trackers.registry import available_providers

            data_sources["integration_types"] = available_providers()

            if operation in ("update", "delete"):
                tdf = await QE.query_db(
                    "SELECT tracker_name, "
                    "coalesce(integration_type, 'devops') as integration_type, "
                    "org_url, pat_token "
                    "FROM trackers ORDER BY tracker_name"
                )
                data_sources["tracker_data"] = (
                    tdf["tracker_name"].tolist() if not tdf.empty else []
                )
                if operation == "update":
                    data_sources["new_tracker_name"] = {}
                    data_sources["integration_type_current"] = {}
                    data_sources["org_url"] = {}
                    # The PAT shows as its opaque enc: value — saving it back
                    # unchanged is a no-op (no double encryption).
                    data_sources["pat_token"] = {}
                    for _, row in tdf.iterrows():
                        tname = row["tracker_name"]
                        data_sources["new_tracker_name"][tname] = tname
                        data_sources["integration_type_current"][tname] = (
                            row["integration_type"] or "devops"
                        )
                        data_sources["org_url"][tname] = row["org_url"] or ""
                        data_sources["pat_token"][tname] = row["pat_token"] or ""

        elif entity_type == "project":
            # Get active customers
            df = await QE.query_db(
                "SELECT customer_id, customer_name FROM customers WHERE is_current = 1"
            )
            data_sources["customer_data"] = (
                df["customer_name"].tolist() if not df.empty else []
            )

            # DevOps work items per customer, for the Git-ID picker. Empty when
            # DevOps isn't connected — the picker then degrades to manual entry.
            data_sources["devops_ids"] = _devops_ids_by_customer(core)

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
                        """SELECT p.project_name, p.git_id, c.customer_name
                           FROM projects p
                           JOIN customers c ON p.customer_id = c.customer_id
                           WHERE p.is_current = 1"""
                    )
                    devops_by_cust = _devops_ids_by_customer(core)
                    data_sources["new_project_name"] = {}
                    # Project-keyed Git-ID picker data: each project carries its
                    # customer's work-item options AND the project's current git
                    # id, since the field's parent is the project (see
                    # DynamicDevOpsSelect's dict response handling).
                    data_sources["devops_ids"] = {}
                    for _, row in full_df.iterrows():
                        pname = row["project_name"]
                        # Plain strings/numbers so widget refresh sets correct values
                        data_sources["new_project_name"][pname] = pname
                        git_val = row["git_id"]
                        data_sources["devops_ids"][pname] = {
                            "items": devops_by_cust.get(row["customer_name"], []),
                            "current": int(git_val) if pd.notna(git_val) else None,
                        }

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

