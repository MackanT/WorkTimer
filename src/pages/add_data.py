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
from .. import clock
from nicegui import ui
from ..core.app import AppCore
from .. import helpers
from ..ui.dynamic_widgets import WIDGET_CLASSES
from ..ui.work_item_forms import _setup_conditional_visibility, _with_loading

_OP_TAB_LABELS = {"reenable": "Re-enable"}

# Field types that take the full form width in the two-column grid.
_WIDE_FIELD_TYPES = {"textarea", "editor_with_preview", "devops_id"}


def _same_place(a: str, b: str) -> bool:
    """The same tracker site/org, however it was typed."""
    def norm(v):
        v = str(v or "").strip().rstrip("/").lower()
        return v if v.startswith("http") else f"https://{v}"
    return norm(a) == norm(b)


def _render_test_connection_button(core, widgets: dict, visible_fn) -> None:
    """'Test connection' on the tracker forms: builds a provider from the
    CURRENT form values (falling back to the stored, decrypted credentials
    for fields left blank/unchanged on the update form) and calls its
    connect() — a credential typo surfaces here instead of as a background
    re-init failure minutes later."""

    async def _test():
        vals = {
            n: (w.value or "") for n, w in widgets.items() if visible_fn(n)
        }
        itype = str(vals.get("integration_type") or "devops")
        org = str(vals.get("org_url") or vals.get("jira_site") or "").strip()
        email = str(vals.get("jira_email") or "").strip()
        token = str(vals.get("jira_api_token") or "").strip()
        pat = str(vals.get("pat_token") or "").strip()
        if pat.startswith("enc:"):
            pat = ""  # the update form's encrypted prefill — use stored

        # Update form: anything blank falls back to the stored credentials.
        tname = str(vals.get("tracker_name") or "").strip()
        needs_stored = not org or (
            not (email and token) if itype == "jira" else not pat
        )
        if tname and needs_stored:
            stored = await core.query_engine.function_db(
                "get_tracker_credentials", tname
            )
            if stored:
                _stype, s_org, s_pat = stored
                # A stored secret is only ever sent back where it came from:
                # with the site/org changed, the token must be typed anew.
                same_place = not org or _same_place(org, s_org)
                org = org or s_org
                if same_place and itype == "jira":
                    s_email, _, s_token = s_pat.partition(":")
                    email = email or s_email
                    token = token or s_token
                elif same_place:
                    pat = pat or s_pat

        if itype == "jira":
            pat = f"{email}:{token}" if email and token else ""
        if not org or not pat:
            ui.notify("Fill in the connection fields first", type="warning")
            return

        row = {
            "customer_name": tname or "connection test",
            "integration_type": itype,
            "org_url": org,
            "pat_token": pat,
            "tracker_project": None,
        }

        def _connect():
            from ..trackers.registry import create_provider_for_row

            provider = create_provider_for_row(row, core.logger)
            if provider is None:
                raise Exception("credentials look incomplete")
            provider.connect()
            return provider.available_projects

        try:
            projects = await asyncio.to_thread(_connect)
        except Exception as e:
            ui.notify(f"Connection failed: {e}", type="negative")
            return
        shown = ", ".join(map(str, projects[:5]))
        if len(projects) > 5:
            shown += f" … (+{len(projects) - 5})"
        ui.notify(f"Connected — projects: {shown}", type="positive")

    btn = ui.button("Test connection", icon="wifi_tethering").props("outline")
    btn.on("click", _with_loading(btn, _test))


async def _projects_of_tracker(core, tracker_name: str) -> tuple[list, str | None]:
    """(projects, note): the projects a tracker connection can see — from a
    live connection of a customer on it, else by connecting with its stored
    credentials (as Test connection does). Where it can't list them (no
    token, unreachable), the projects its customers use, with a note why."""
    eng = getattr(core, "tracker_engine", None)
    live = eng.get_available_projects() if eng is not None else {}
    details = await core.query_engine.function_db("get_current_customer_details")
    on_tracker = details[details["tracker_name"] == tracker_name]
    for customer in on_tracker["customer_name"]:
        if live.get(customer):
            return list(live[customer]), None
    in_use = sorted({p for p in on_tracker["tracker_project"] if p})
    stored = await core.query_engine.function_db("get_tracker_credentials", tracker_name)
    if not stored or not stored[1] or not stored[2]:
        return in_use, "No token stored for this tracker: only projects already in use"
    row = {"customer_name": tracker_name, "integration_type": stored[0], "org_url": stored[1],
           "pat_token": stored[2], "tracker_project": None}

    def _connect():
        from ..trackers.registry import create_provider_for_row

        provider = create_provider_for_row(row, core.logger)
        if provider is None:
            return []
        provider.connect()
        return list(provider.available_projects)

    try:
        return await asyncio.to_thread(_connect), None
    except Exception as e:
        core.logger.warning(f"Could not list the projects of tracker '{tracker_name}': {e}")
        return in_use, "Tracker not reachable: only projects already in use"


def _wire_tracker_projects(core, widgets: dict, data_fetcher) -> None:
    """The Update form's Tracker project follows the selected TRACKER (its
    projects, fetched once per tracker per dialog), with the customer's own
    project preselected while its own tracker is selected. A project that
    can't be listed (offline, no token) still shows — saving keeps it — and
    a hint says when the list is only the projects already in use."""
    if not all(n in widgets for n in ("customer_name", "tracker_name", "tracker_project")):
        return
    customer, tracker, project = (widgets[n] for n in ("customer_name", "tracker_name",
                                                       "tracker_project"))
    cache: dict = {}
    latest = {"n": 0}  # a customer change and its tracker change both refresh: the last wins

    async def refresh(_=None):
        latest["n"] = n = latest["n"] + 1
        name = tracker.value
        if name and name not in cache:
            cache[name] = await _projects_of_tracker(core, name)
        if n != latest["n"]:
            return
        options, note = cache[name] if name else ([], None)
        options = list(options)
        own_tracker = (await data_fetcher("tracker_current") or {}).get(customer.value)
        own_project = (await data_fetcher("tracker_project_current") or {}).get(customer.value)
        if n != latest["n"]:
            return
        value = project.value
        if name and name == own_tracker:
            value = own_project or None
        elif value not in options:
            value = None
        if value and value not in options:
            options.append(value)
        project.widget.options = options
        project.widget.value = value
        if note:
            project.widget.props(f'hint="{note}"')
        else:
            project.widget.props(remove="hint")
        project.widget.update()

    customer.widget.on_value_change(refresh)
    tracker.widget.on_value_change(refresh)


def _amount(value) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _difference(value) -> str:
    return f"{value:+,.2f}".replace(",", " ")


def _rate(wage: int, currency: str) -> str:
    return f"{wage:,} {currency}".replace(",", " ")


def _effect_rows(plan: dict) -> list[tuple[str, str]]:
    """What saving re-prices, as (label, value) rows for a confirmation."""
    n, currency = plan["entries"], plan["currency"]
    if not n:
        return [("Time entries re-priced", "none")]
    first, last = plan["first_day"], plan["last_day"]
    span = f"{first:%Y-%m-%d}" + ("" if first == last else f" – {last:%Y-%m-%d}")
    return [
        ("Time entries re-priced", f"{n}, dated {span}"),
        ("Amount before", f"{_amount(plan['cost_before'])} {currency}"),
        ("Amount after", f"{_amount(plan['cost_after'])} {currency}"),
        ("Difference", f"{_difference(plan['cost_after'] - plan['cost_before'])} {currency}"),
    ]


_INVOICED_NOTE = ("Reports and the Time Tracker show the new amounts, also for time "
                  "already invoiced.")


async def _confirm(title: str, rows: list[tuple[str, str]], ok: str, note: str = None) -> bool:
    muted = helpers.UI_STYLES.get_layout_classes("muted_text")
    with ui.dialog() as dialog, ui.card().classes("p-4 gap-3").style("max-width: 34rem"):
        ui.label(title).classes("text-base font-semibold")
        with ui.grid(columns="auto auto").classes("gap-x-6 gap-y-1 text-sm"):
            for label, value in rows:
                ui.label(label).classes(muted)
                ui.label(value).classes("tabular-nums")
        if note:
            ui.label(note).classes("text-xs " + muted)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
            ui.button(ok, on_click=lambda: dialog.submit(True)).props("color=primary no-caps")
    confirmed = await dialog
    dialog.delete()
    return bool(confirmed)


# The Update form's rate fields → preview_customer_rate's parameters.
_RATE_FIELDS = {"customer_name": "customer_name", "wage": "wage", "rate_from": "valid_from"}


def _rate_values(values: dict) -> dict | None:
    """The preview's arguments from the form's values; None until all are set."""
    args = {param: values.get(field) for field, param in _RATE_FIELDS.items()}
    return None if any(v in (None, "") for v in args.values()) else args


def _rate_table(periods: list, currency: str, accent: str, changed=(), on_remove=None,
                effects=None) -> None:
    """Rate periods as From / To / Rate rows — the `changed` ones stand out.
    With `on_remove`, every change after the first has a ✕; with `effects`
    (per period: entries re-priced, cost before, after), what saving
    re-prices shows beside each changed period."""
    muted = helpers.UI_STYLES.get_layout_classes("muted_text")
    heads = ["From", "To", "Rate"]
    if effects is not None:
        heads += ["Re-priced", "Change"]
    if on_remove:
        heads.append("")
    with ui.grid(columns=" ".join(["auto"] * len(heads))).classes(
            "gap-x-4 gap-y-0 items-center text-xs leading-5"):
        for head in heads:
            ui.label(head).classes(muted + (" text-right" if head in ("Re-priced", "Change") else ""))
        for i, (start, end, wage) in enumerate(periods):
            mark = f" font-semibold text-{accent}" if (start, end, wage) in changed else ""
            ui.label(f"{start:%Y-%m-%d}").classes(mark)
            ui.label(f"{end:%Y-%m-%d}" if end else "ongoing").classes(mark)
            ui.label(_rate(wage, currency)).classes("text-right tabular-nums" + mark)
            if effects is not None:
                n, before, after = effects[i]
                shown = n or mark
                ui.label(f"{n} {'entry' if n == 1 else 'entries'}" if shown else "").classes(
                    "text-right tabular-nums" + mark)
                ui.label(_difference(after - before) if n else ("–" if mark else "")).classes(
                    "text-right tabular-nums" + mark)
            if not on_remove:
                continue
            if i == 0:
                ui.label("")
            else:
                ui.button(icon="close",
                          on_click=lambda _=None, s=start, w=periods[i - 1][2]: on_remove(s, w)
                          ).props("flat dense round size=xs color=grey-6").tooltip(
                    "Remove this change: the earlier rate applies again")


def _render_rate_preview(core, widgets: dict) -> None:
    """Under the Update form: the customer's rates (each change removable),
    and — once the rate or its date is changed — the rates after saving and
    the logged time re-priced. Kept current as the fields change, in a
    steady space so the dialog doesn't jump while typing."""
    muted = helpers.UI_STYLES.get_layout_classes("muted_text")
    accent = core.theme.get("accent")
    # Framed like the form's read-only fields (Quasar's dashed outline), and
    # shown once there is something to frame.
    box = ui.column().classes("w-full gap-1 items-center rounded").style(
        "border: 1px dashed rgba(128, 128, 128, 0.5); padding: 0.5rem 0.75rem")
    box.set_visibility(False)
    latest = {"n": 0}  # an older preview finishing late must not win

    async def remove(start, earlier_wage):
        name = widgets["customer_name"].value
        args = {"customer_name": name, "wage": earlier_wage, "valid_from": start}
        try:
            plan = await core.query_engine.function_db("preview_customer_rate", **args)
            rows = [(f"Rate from {start:%Y-%m-%d}",
                     f"{_rate(earlier_wage, plan['currency'])} (the earlier rate)"),
                    *_effect_rows(plan)]
            if not await _confirm(f"Remove the rate change on {start:%Y-%m-%d}?", rows, "Remove",
                                  note=_INVOICED_NOTE if plan["entries"] else None):
                return
            plan = await core.query_engine.function_db("set_customer_rate", **args)
        except Exception as e:
            ui.notify(f"Error: {e}", type="negative")
            return
        core.logger.info(f"Removed the rate change on {start} for '{name}'")
        ui.notify(f"Rate change on {start:%Y-%m-%d} removed", color="positive")
        core.event_bus.emit("ui_refresh_requested")
        # The form's rate is today's again — saving it untouched changes nothing.
        from ..pg_database import _rate_on

        widgets["wage"].value = _rate_on(plan["after"], clock.today_local())
        widgets["rate_from"].value = clock.today_local().isoformat()
        await refresh()

    async def refresh(_=None):
        latest["n"] = n = latest["n"] + 1
        args = _rate_values({k: widgets[k].value for k in _RATE_FIELDS if k in widgets})
        if args is None:
            box.clear()
            box.set_visibility(False)
            return
        try:
            plan = await core.query_engine.function_db("preview_customer_rate", **args)
        except Exception as e:
            plan = e
        if n != latest["n"]:
            return
        box.clear()
        box.set_visibility(True)
        with box:
            if isinstance(plan, Exception):
                ui.label(str(plan)).classes("text-xs text-negative")
                return
            before, after, currency = plan["before"], plan["after"], plan["currency"]
            changed = after != before or plan["entries"]
            rows = len(before) + 3  # title, header, the rows, and one a change can add
            with ui.row().classes("w-full gap-10 items-start justify-center no-wrap").style(
                    f"min-height: {rows * 1.25}rem"):
                with ui.column().classes("gap-0"):
                    ui.label("Hourly rates").classes("text-xs font-semibold leading-5")
                    _rate_table(before, currency, accent, on_remove=remove)
                with ui.column().classes("gap-0"):
                    ui.label("After saving").classes("text-xs font-semibold leading-5")
                    if changed:
                        _rate_table(after, currency, accent,
                                    changed=[p for p in after if p not in before],
                                    effects=plan["effects"])
                    else:
                        ui.label("Change the rate or its date to see the result here.").classes(
                            "text-xs leading-5 " + muted)

    for name in _RATE_FIELDS:
        if name in widgets:
            widgets[name].widget.on_value_change(refresh)


async def _confirm_rate_change(core, values: dict) -> bool:
    """Saving re-prices logged time: say what changes, and ask first."""
    args = _rate_values(values)
    if args is None:
        return True
    plan = await core.query_engine.function_db("preview_customer_rate", **args)
    if not plan["entries"]:
        return True
    rows = [("New rate", f"{_rate(plan['wage'], plan['currency'])} from "
                         f"{plan['valid_from']:%Y-%m-%d}"), *_effect_rows(plan)]
    return await _confirm(f"Change the hourly rate of {plan['customer_name']}?", rows,
                          "Change rate", note=_INVOICED_NOTE)


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
    # A field marked `backend:` exists only there (a customer's currency: Postgres).
    backend = getattr(getattr(core.query_engine, "db", None), "backend", "sqlite")
    fields = [f for f in fields if f.get("backend", backend) == backend]
    action = form_config.get("action", {})

    data_sources = await prepare_data_sources(core, entity_type, operation)
    helpers.assign_dynamic_options(fields, data_sources=data_sources)

    widgets = {}
    dynamic_widgets = []
    parent_map = {}

    def _visible(name):
        w = widgets.get(name)
        return w is not None and getattr(w.widget, "visible", True)

    async def on_submit():
        # Hidden fields (visible_when for another tracker type) neither
        # validate nor submit — their stale values must not reach the DB.
        required_fields = [
            f["name"]
            for f in fields
            if not f.get("optional", False) and _visible(f["name"])
        ]
        if not helpers.check_input(widgets, required_fields):
            return
        kwargs = {
            name: widget.value
            for name, widget in widgets.items()
            if _visible(name)
        }
        if entity_type == "customer" and operation == "update" and "wage" in kwargs:
            try:
                if not await _confirm_rate_change(core, kwargs):
                    return
            except Exception as e:
                ui.notify(f"Error: {e}", type="negative")
                return
        # Snapshot before the values get cleared below — used to decide whether
        # this change touched tracker connections (see re-init at the end).
        devops_touched = entity_type == "tracker" or (
            entity_type == "customer"
            and (
                operation in ("disable", "reenable")
                or bool(kwargs.get("tracker_name"))
                or bool(kwargs.get("tracker_project"))
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
            # app restart. force_tracker_reinit() bypasses the retry cooldown and
            # re-inits in the background.
            if devops_touched:
                core.logger.info(
                    f"Tracker config changed ({entity_type}.{operation}) — "
                    "re-initializing tracker connections"
                )
                core.force_tracker_reinit()
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

        if entity_type == "customer" and operation == "update" and "wage" in widgets:
            _render_rate_preview(core, widgets)
        if entity_type == "customer" and operation == "update":
            _wire_tracker_projects(core, widgets, data_fetcher)

        with ui.row().classes("w-full justify-end gap-2"):
            if entity_type == "tracker" and operation in ("add", "update"):
                _render_test_connection_button(core, widgets, _visible)

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

    # visible_when conditions (per-type credential fields on the tracker
    # forms) — same mechanism the work-item forms use.
    _setup_conditional_visibility(
        widgets, {f["name"]: f for f in fields}, set()
    )

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
    eng = getattr(core, "tracker_engine", None)
    return eng.get_work_item_options() if eng is not None else {}


async def prepare_data_sources(core: AppCore, entity_type: str, operation: str) -> dict:
    """Prepare data sources for entity forms"""
    QE = core.query_engine
    data_sources = {}

    try:
        if entity_type == "customer":
            # Trackers a customer can link to (credentials live on the
            # tracker entity, not the customer).
            tdf = await QE.function_db("get_tracker_names")
            data_sources["tracker_data"] = (
                tdf["tracker_name"].tolist() if not tdf.empty else []
            )

            if operation in ["update", "disable"]:
                # Get active customers
                df = await QE.function_db("get_current_customer_names")
                data_sources["customer_data"] = (
                    df["customer_name"].tolist() if not df.empty else []
                )

                if operation == "update":
                    # For update, we need current values per customer
                    full_df = await QE.function_db("get_current_customer_details")
                    data_sources["new_customer_name"] = {}
                    data_sources["tracker_current"] = {}
                    # Current project per customer (preselects the picker).
                    data_sources["tracker_project_current"] = {}
                    data_sources["expected_work_pct"] = {}
                    data_sources["color"] = {}
                    data_sources["wage_current"] = {}  # the rate in force today (Postgres)
                    for _, row in full_df.iterrows():
                        cname = row["customer_name"]
                        data_sources["new_customer_name"][cname] = cname
                        data_sources["tracker_current"][cname] = (
                            row["tracker_name"] or ""
                        )
                        data_sources["tracker_project_current"][cname] = (
                            row["tracker_project"] or ""
                        )
                        data_sources["expected_work_pct"][cname] = (
                            float(row["expected_work_pct"])
                            if pd.notna(row["expected_work_pct"]) else 0
                        )
                        data_sources["color"][cname] = row["color"] or ""
                        if pd.notna(row.get("wage")):
                            data_sources["wage_current"][cname] = int(row["wage"])

            elif operation == "reenable":
                # Get customers that are disabled and have no active entry
                df = await QE.function_db("get_disabled_customer_names")
                data_sources["customer_data"] = sorted(
                    df["customer_name"].tolist() if not df.empty else []
                )

            # Today's date for start_date
            data_sources["today"] = clock.today_local().isoformat()

        elif entity_type == "tracker":
            # Registered tracker providers feed the "Type" selector — a new
            # provider module (e.g. Jira) appears here automatically.
            from ..trackers.registry import available_providers

            data_sources["integration_types"] = available_providers()

            if operation in ("update", "delete"):
                tdf = await QE.function_db("get_trackers")
                data_sources["tracker_data"] = (
                    tdf["tracker_name"].tolist() if not tdf.empty else []
                )
                if operation == "update":
                    from ..pat_crypto import decrypt_pat

                    db_file = core.query_engine.file_name
                    data_sources["new_tracker_name"] = {}
                    data_sources["integration_type_current"] = {}
                    # Credential prefills are PER TYPE, and the SECRET fields
                    # (PAT / API token) always prefill blank — blank means
                    # "keep the stored one", and showing the enc: blob would
                    # only suggest a wrong format. The always-"" maps still
                    # matter: switching trackers clears a typed-but-unsaved
                    # value via the parent refresh.
                    data_sources["org_url"] = {}
                    data_sources["pat_token"] = {}
                    data_sources["jira_site"] = {}
                    data_sources["jira_email"] = {}
                    data_sources["jira_api_token"] = {}
                    # Not secret — prefill the stored expiry date as-is.
                    data_sources["token_expires"] = {}
                    for _, row in tdf.iterrows():
                        tname = row["tracker_name"]
                        itype = row["integration_type"] or "devops"
                        data_sources["new_tracker_name"][tname] = tname
                        data_sources["integration_type_current"][tname] = itype
                        data_sources["token_expires"][tname] = (
                            row["token_expires"] or ""
                        )
                        for key in ("org_url", "pat_token", "jira_site",
                                    "jira_email", "jira_api_token"):
                            data_sources[key][tname] = ""
                        if itype == "jira":
                            data_sources["jira_site"][tname] = (
                                row["org_url"] or ""
                            )
                            # The email half of the packed credential is not
                            # secret — prefill it.
                            pat = decrypt_pat(
                                row["pat_token"] or "", db_file, core.logger
                            )
                            data_sources["jira_email"][tname] = (
                                pat.partition(":")[0]
                            )
                        else:
                            data_sources["org_url"][tname] = row["org_url"] or ""

        elif entity_type == "project":
            # Get active customers
            df = await QE.function_db("get_current_customer_names")
            data_sources["customer_data"] = (
                df["customer_name"].tolist() if not df.empty else []
            )

            # DevOps work items per customer, for the Git-ID picker. Empty when
            # DevOps isn't connected — the picker then degrades to manual entry.
            data_sources["devops_ids"] = _devops_ids_by_customer(core)

            if operation in ["update", "disable"]:
                # Get active projects grouped by customer (for parent-dependent dropdown)
                grouped_df = await QE.function_db(
                    "get_current_projects_with_customer"
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
                    full_df = await QE.function_db(
                        "get_current_projects_with_customer"
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
                dis_df = await QE.function_db(
                    "get_disabled_projects_with_customer"
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

            data_sources["today"] = clock.today_local().isoformat()

        elif entity_type == "bonus":
            # Get active customers and projects
            cust_df = await QE.function_db("get_current_customer_names")
            proj_df = await QE.function_db("get_current_project_names")
            data_sources["customer_data"] = (
                cust_df["customer_name"].tolist() if not cust_df.empty else []
            )
            data_sources["project_data"] = (
                proj_df["project_name"].tolist() if not proj_df.empty else []
            )
            data_sources["today"] = clock.today_local().isoformat()

    except Exception as e:
        core.logger.error(
            f"Error preparing data sources for {entity_type}.{operation}: {e}"
        )

    return data_sources

