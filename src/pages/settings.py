"""
Settings Page

Form-driven editor for YAML configuration files:
  - task_visuals.yml   (customer/project icon + color mappings)
  - devops_contacts.yml (per-customer contacts, assignees, default)
  - config_theme.yml    (app color palette)

No raw YAML exposed — users fill in fields and press Save.
"""

from pathlib import Path
import yaml
from nicegui import ui
from ..core.app import AppCore
from ..ui.elements import toolbar, page_card

# ── Quasar colour palette offered in dropdowns ──────────────────────────────
QUASAR_COLORS = [
    "red",
    "pink",
    "purple",
    "deep-purple",
    "indigo",
    "blue",
    "light-blue",
    "cyan",
    "teal",
    "green",
    "light-green",
    "lime",
    "yellow",
    "amber",
    "orange",
    "deep-orange",
    "brown",
    "grey",
    "blue-grey",
]


def _config_path(core: AppCore, filename: str) -> Path:
    return core.config_loader.config_folder / filename


def _load_yaml(path: Path) -> dict:
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(
            data, f, allow_unicode=True, default_flow_style=False, sort_keys=False
        )


# ─────────────────────────────────────────────────────────────────────────────
# Task Visuals tab
# ─────────────────────────────────────────────────────────────────────────────


def _render_visuals_section(
    core: AppCore,
    section: str,  # "customers" or "projects"
    visuals_path: Path,
    container: ui.element,
):
    """Render one section (customers or projects) of task_visuals.yml."""

    def _reload_table():
        container.clear()
        data = _load_yaml(visuals_path)
        entries = data.get("visual", {}).get(section, {})
        with container:
            if not entries:
                ui.label("No entries yet.").classes("text-slate-400 text-sm")
                return
            cols = [
                {
                    "name": "name",
                    "label": "Name",
                    "field": "name",
                    "align": "left",
                    "sortable": True,
                },
                {"name": "icon", "label": "Icon", "field": "icon", "align": "left"},
                {"name": "color", "label": "Color", "field": "color", "align": "left"},
                {"name": "del", "label": "", "field": "del", "align": "center"},
            ]
            rows = [
                {"name": k, "icon": v.get("icon", ""), "color": v.get("color", "")}
                for k, v in entries.items()
            ]

            with ui.table(columns=cols, rows=rows, row_key="name").classes(
                "w-full"
            ) as tbl:
                tbl.add_slot(
                    "body-cell-icon",
                    """
                    <q-td :props="props">
                        <q-icon :name="props.value" size="sm" class="mr-1"/>
                        <span class="text-xs text-slate-400">{{ props.value }}</span>
                    </q-td>
                """,
                )
                tbl.add_slot(
                    "body-cell-color",
                    """
                    <q-td :props="props">
                        <q-badge :color="props.value" :label="props.value"/>
                    </q-td>
                """,
                )
                tbl.add_slot(
                    "body-cell-del",
                    """
                    <q-td :props="props" auto-width>
                        <q-btn flat dense round icon="delete" color="negative"
                               @click="$parent.$emit('delete', props.row)"/>
                    </q-td>
                """,
                )

                def on_delete(e):
                    name = e.args.get("name", "")
                    data2 = _load_yaml(visuals_path)
                    data2.setdefault("visual", {}).setdefault(section, {}).pop(
                        name, None
                    )
                    _save_yaml(visuals_path, data2)
                    ui.notify(f"Deleted '{name}'", type="warning")
                    _reload_table()

                tbl.on("delete", on_delete)

    _reload_table()


async def _render_task_visuals_tab(core: AppCore):
    visuals_path = _config_path(core, "task_visuals.yml")

    for section in ("customers", "projects"):
        with ui.card().props("flat").classes("w-full rounded-lg mb-4"):
            ui.label(section.capitalize()).classes(
                "text-base font-semibold text-amber-400 mb-2"
            )

            table_container = ui.element("div").classes("w-full")
            _render_visuals_section(core, section, visuals_path, table_container)

            ui.separator().classes("my-3")
            ui.label("Add / Update entry").classes("text-sm text-slate-400")

            with ui.row().classes("items-end gap-3 flex-wrap"):
                name_in = ui.input("Name").classes("w-48").props("dense outlined")
                icon_in = (
                    ui.input("Icon (Material Design)", placeholder="e.g. apartment")
                    .classes("w-48")
                    .props("dense outlined")
                )
                icon_preview = ui.icon("help_outline", size="sm").classes(
                    "text-amber-400 self-center"
                )
                color_in = (
                    ui.select(QUASAR_COLORS, label="Color", value="indigo")
                    .classes("w-40")
                    .props("dense outlined")
                )

                def _update_preview():
                    icon_preview.set_name(icon_in.value or "help_outline")

                icon_in.on("update:model-value", lambda: _update_preview())

                def _save(sec=section, tc=table_container):
                    name = (name_in.value or "").strip()
                    icon = (icon_in.value or "").strip()
                    color = color_in.value or "indigo"
                    if not name or not icon:
                        ui.notify("Name and Icon are required.", type="warning")
                        return
                    data = _load_yaml(visuals_path)
                    data.setdefault("visual", {}).setdefault(sec, {})[name] = {
                        "icon": icon,
                        "color": color,
                    }
                    _save_yaml(visuals_path, data)
                    ui.notify(f"Saved '{name}'", type="positive")
                    name_in.value = ""
                    icon_in.value = ""
                    icon_preview.set_name("help_outline")
                    _render_visuals_section(core, sec, visuals_path, tc)

                ui.button("Save", icon="save", on_click=_save).props(
                    "color=primary dense"
                )


# ─────────────────────────────────────────────────────────────────────────────
# DevOps Contacts tab
# ─────────────────────────────────────────────────────────────────────────────


async def _render_devops_contacts_tab(core: AppCore):
    path = _config_path(core, "devops_contacts.yml")

    # ── customer selector card ─────────────────────────────────────────────
    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4 mb-4"):
        ui.label("Customers").classes("text-base font-semibold text-amber-400 mb-3")

        d = _load_yaml(path)
        customer_names = list(d.get("customers", {}).keys())

        with ui.row().classes("items-end gap-3 flex-wrap"):
            cust_sel = (
                ui.select(
                    customer_names,
                    label="Select Customer",
                    value=customer_names[0] if customer_names else None,
                )
                .props("dense outlined")
                .classes("w-56")
            )
            new_cust_in = (
                ui.input("New Customer Name").props("dense outlined").classes("w-52")
            )

            def _add_customer():
                name = (new_cust_in.value or "").strip()
                if not name:
                    return
                dd = _load_yaml(path)
                if name not in dd.setdefault("customers", {}):
                    dd["customers"][name] = {
                        "contacts": [],
                        "assignees": [],
                        "default_assignee": "",
                    }
                    _save_yaml(path, dd)
                new_cust_in.value = ""
                opts = list(_load_yaml(path).get("customers", {}).keys())
                cust_sel.options = opts
                cust_sel.value = name
                ui.notify(f"Customer '{name}' added — select to edit.", type="positive")
                _reload_detail()

            ui.button("Add Customer", icon="add", on_click=_add_customer).props(
                "color=primary dense"
            )

    # ── detail card ───────────────────────────────────────────────────────
    detail = ui.card().props("flat bordered").classes("w-full rounded-lg p-4")

    def _reload_detail():
        detail.clear()
        customer = cust_sel.value
        if not customer:
            return
        dd = _load_yaml(path)
        cdata = dd.get("customers", {}).get(customer, {})

        with detail:
            ui.label(customer).classes("text-base font-semibold text-amber-400 mb-3")

            for field_key, field_label in [
                ("contacts", "Contacts"),
                ("assignees", "Assignees (email)"),
            ]:
                ui.label(field_label).classes(
                    "text-sm font-semibold text-slate-300 mt-2 mb-1"
                )
                items = cdata.get(field_key, [])

                with ui.row().classes("flex-wrap gap-2 mb-2"):
                    for item in items:
                        with ui.element("div").classes(
                            "flex items-center bg-slate-700 rounded-full px-3 py-1 gap-1"
                        ):
                            ui.label(item).classes("text-sm text-white")

                            def _remove(it=item, fk=field_key):
                                ddd = _load_yaml(path)
                                lst = (
                                    ddd.get("customers", {})
                                    .get(customer, {})
                                    .get(fk, [])
                                )
                                if it in lst:
                                    lst.remove(it)
                                _save_yaml(path, ddd)
                                _reload_detail()

                            ui.button(icon="close", on_click=_remove).props(
                                "dense flat round size=xs color=negative"
                            )

                add_in = (
                    ui.input(f"Add {field_label.lower()}")
                    .props("dense outlined")
                    .classes("w-64")
                )

                def _add_item(fk=field_key, ai=add_in):
                    v = (ai.value or "").strip()
                    if not v:
                        return
                    ddd = _load_yaml(path)
                    lst = (
                        ddd.setdefault("customers", {})
                        .setdefault(customer, {})
                        .setdefault(fk, [])
                    )
                    if v not in lst:
                        lst.append(v)
                    _save_yaml(path, ddd)
                    ai.value = ""
                    _reload_detail()

                with ui.row().classes("items-center gap-2 mb-2"):
                    add_in
                    ui.button(icon="add", on_click=_add_item).props(
                        "dense flat color=primary"
                    )

                ui.separator().classes("my-3")

            # default assignee
            ui.label("Default Assignee").classes(
                "text-sm font-semibold text-slate-300 mb-1"
            )
            current_default = cdata.get("default_assignee", "")
            assignees = cdata.get("assignees", [])
            default_sel = (
                ui.select(assignees, label="Default Assignee", value=current_default)
                .props("dense outlined")
                .classes("w-64")
            )

            def _save_default():
                ddd = _load_yaml(path)
                ddd.setdefault("customers", {}).setdefault(customer, {})[
                    "default_assignee"
                ] = default_sel.value
                _save_yaml(path, ddd)
                ui.notify("Default assignee saved", type="positive")

            ui.button("Set Default", icon="save", on_click=_save_default).props(
                "color=primary dense"
            ).classes("mt-1")

    cust_sel.on("update:model-value", lambda: _reload_detail())
    _reload_detail()


# ─────────────────────────────────────────────────────────────────────────────
# Theme tab
# ─────────────────────────────────────────────────────────────────────────────


async def _render_theme_tab(core: AppCore):
    theme_path = _config_path(core, "config_theme.yml")
    data = _load_yaml(theme_path)
    colors = data.get("colors", {})

    HEX_FIELDS = [
        "primary",
        "secondary",
        "dark",
        "dark_page",
        "positive",
        "negative",
        "info",
        "warning",
    ]
    CLASS_FIELDS = ["accent", "muted", "divider", "toolbar_bg", "nav_bg", "border"]

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        ui.label("Hex Colors").classes("text-base font-semibold text-amber-400 mb-1")
        ui.label(
            "Used directly in Quasar's color system (buttons, notifications, etc.)"
        ).classes("text-xs text-slate-400 mb-3")

        hex_inputs: dict = {}
        with ui.grid(columns=2).classes("w-full gap-3 mb-4"):
            for key in HEX_FIELDS:
                val = colors.get(key, "")
                inp = (
                    ui.input(label=key, value=val)
                    .props("dense outlined")
                    .classes("w-full")
                )
                hex_inputs[key] = inp

        ui.separator().classes("my-3")
        ui.label("Tailwind / Quasar Classes").classes(
            "text-base font-semibold text-amber-400 mb-2"
        )
        ui.label(
            "These Tailwind/Quasar color class names are used in .classes() throughout the UI."
        ).classes("text-xs text-slate-400 mb-3")

        class_inputs: dict = {}
        with ui.grid(columns=2).classes("w-full gap-3"):
            for key in CLASS_FIELDS:
                val = colors.get(key, "")
                inp = (
                    ui.input(label=key, value=val)
                    .props("dense outlined")
                    .classes("w-full")
                )
                class_inputs[key] = inp

        def _save_theme():
            d = _load_yaml(theme_path)
            d.setdefault("colors", {})
            for k, w in {**hex_inputs, **class_inputs}.items():
                d["colors"][k] = w.value
            _save_yaml(theme_path, d)
            ui.notify("Theme saved — restart to apply changes", type="positive")

        ui.button("Save Theme", icon="save", on_click=_save_theme).props(
            "color=primary"
        ).classes("mt-4")


# ─────────────────────────────────────────────────────────────────────────────
# Page entry point
# ─────────────────────────────────────────────────────────────────────────────


async def settings_page():
    """Settings page — form-driven YAML config editor."""
    core = await AppCore.get_or_initialize()

    with toolbar(core.theme):
        ui.icon("tune", size="md").classes("text-amber-400")
        ui.label("Settings").classes("text-h5 text-white font-medium")
        ui.space()
        with (
            ui.tabs(value="visuals")
            .props(
                f'horizontal dense active-color="{core.theme.get("accent")}" indicator-color="{core.theme.get("accent")}"'
            )
            .classes("text-xs text-white uppercase tracking-wide")
        ) as tabs:
            # ui.tab("visuals", label="Task Visuals", icon="palette")
            ui.tab("contacts", label="DevOps Contacts", icon="contacts")
            ui.tab("theme", label="Theme", icon="color_lens")

    with page_card(scrollable=False):
        with (
            ui.tab_panels(tabs, value="visuals")
            .classes("w-full h-full")
            .style("background: transparent;")
        ):
            # with ui.tab_panel("visuals").classes("p-0 h-full"):
            #     with ui.scroll_area().classes("w-full h-full"):
            #         with ui.column().classes("w-full gap-4 p-2"):
            #             await _render_task_visuals_tab(core)

            with ui.tab_panel("contacts").classes("p-0 h-full"):
                with ui.scroll_area().classes("w-full h-full"):
                    with ui.column().classes("w-full gap-4 p-2"):
                        await _render_devops_contacts_tab(core)

            with ui.tab_panel("theme").classes("p-0 h-full"):
                with ui.scroll_area().classes("w-full h-full"):
                    with ui.column().classes("w-full gap-4 p-2"):
                        await _render_theme_tab(core)
