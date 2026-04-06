"""
Settings Page

Sidebar-navigation layout with three sections:
  - DevOps Contacts   (customer list / contact detail)
  - DevOps Tags       (tag table + add/edit dialog)
  - Theme             (colour pickers for the app palette)

Add and Reset buttons live next to each section name in the left sidebar.
DevOps sync buttons live in the toolbar.
"""

from pathlib import Path
import asyncio
import re
import yaml
from nicegui import ui
from ..core.app import AppCore
from ..ui.elements import toolbar, page_card
from ..helpers import UI_STYLES

# ── Quasar colour palette offered in dropdowns ──────────────────────────────
QUASAR_COLORS = [
    "red", "pink", "purple", "deep-purple", "indigo",
    "blue", "light-blue", "cyan", "teal", "green",
    "light-green", "lime", "yellow", "amber", "orange",
    "deep-orange", "brown", "grey", "blue-grey",
]

# ── Material icon presets for DevOps tags ────────────────────────────────────
_ICON_PRESETS = [
    ("Bug",         "bug_report"),
    ("Feature",     "star"),
    ("Task",        "task_alt"),
    ("Sprint",      "sprint"),
    ("Epic",        "auto_awesome"),
    ("User Story",  "person"),
    ("Improvement", "trending_up"),
    ("Label",       "label"),
    ("Flag",        "flag"),
    ("Code",        "code"),
]
_ICON_CUSTOM = "__custom__"
ICON_SELECT_OPTIONS: dict[str, str] = {
    val: f"{lbl}  ({val})" for lbl, val in _ICON_PRESETS
}
ICON_SELECT_OPTIONS[_ICON_CUSTOM] = "Custom..."
_ICON_FIRST = next(iter(ICON_SELECT_OPTIONS))

# ── Tailwind token → hex (app-relevant palette) ──────────────────────────────
TAILWIND_TOKEN_HEX: dict[str, str] = {
    "slate-50": "#f8fafc",  "slate-100": "#f1f5f9",  "slate-200": "#e2e8f0",
    "slate-300": "#cbd5e1", "slate-400": "#94a3b8",  "slate-500": "#64748b",
    "slate-600": "#475569", "slate-700": "#334155",  "slate-800": "#1e293b",
    "slate-900": "#0f172a", "slate-950": "#020617",
    "amber-100": "#fef3c7", "amber-200": "#fde68a",  "amber-300": "#fcd34d",
    "amber-400": "#fbbf24", "amber-500": "#f59e0b",  "amber-600": "#d97706",
    "amber-700": "#b45309",
    "emerald-400": "#34d399", "emerald-500": "#10b981",
    "red-400": "#f87171",   "red-500": "#ef4444",    "red-600": "#dc2626",
    "sky-400": "#38bdf8",   "sky-500": "#0ea5e9",
    "white": "#ffffff",     "black": "#000000",
}


def _hex_of_token(token: str) -> str:
    return TAILWIND_TOKEN_HEX.get(token.split("/")[0], "#94a3b8")


def _nearest_tailwind_token(hex_color: str) -> str:
    m = re.match(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})", hex_color)
    if not m:
        return hex_color
    r, g, b = int(m[1], 16), int(m[2], 16), int(m[3], 16)
    best, best_dist = None, float("inf")
    for token, h in TAILWIND_TOKEN_HEX.items():
        m2 = re.match(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})", h)
        if not m2:
            continue
        dist = (r - int(m2[1], 16))**2 + (g - int(m2[2], 16))**2 + (b - int(m2[3], 16))**2
        if dist < best_dist:
            best_dist, best = dist, token
    return best or hex_color


def _fmt_time(dt) -> str:
    if dt is None:
        return "Never"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


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
# DevOps Contacts panel
# ─────────────────────────────────────────────────────────────────────────────


async def _render_devops_contacts_tab(core: AppCore, reg: dict):
    # reg["list_container"] must be set by settings_page before calling this.
    path = _config_path(core, "devops_contacts.yml")
    selected: dict = {"customer": None}
    contacts_template = path.parent / "devops_contacts.yml.template"

    def _reset_contacts():
        import shutil
        if contacts_template.exists():
            shutil.copy2(contacts_template, path)
            core.config_loader.reload_config("devops_contacts.yml")
            selected["customer"] = None
            _rebuild_customer_list()
            _reload_detail()
            ui.notify("Contacts reset to defaults", type="warning")
        else:
            ui.notify("Template file not found", type="negative")

    # ── detail view ───────────────────────────────────────────────────────────
    with ui.scroll_area().classes("w-full h-full"):
        detail_col = ui.column().classes("w-full p-4 gap-4")

    # ── Add-customer dialog ───────────────────────────────────────────────────
    with ui.dialog() as add_cust_dlg, ui.card():
        ui.label("Add Customer").classes("text-base font-bold mb-2")
        new_cust_in = (
            ui.input("Customer name")
            .props("outlined dense autofocus")
            .classes("w-64")
        )
        with ui.row().classes("justify-end gap-2 mt-3"):
            ui.button("Cancel", on_click=add_cust_dlg.close).props("flat dense")

            def _do_add_customer():
                name = (new_cust_in.value or "").strip()
                if not name:
                    return
                dd = _load_yaml(path)
                if name not in dd.setdefault("customers", {}):
                    dd["customers"][name] = {
                        "contacts": [], "assignees": [], "default_assignee": "",
                    }
                    _save_yaml(path, dd)
                    core.config_loader.reload_config("devops_contacts.yml")
                new_cust_in.value = ""
                add_cust_dlg.close()
                selected["customer"] = name
                _rebuild_customer_list()
                _reload_detail()
                ui.notify(f"Customer '{name}' added", type="positive")

            ui.button("Add", icon="add", on_click=_do_add_customer).props(
                "color=primary dense"
            )

    # ── expose actions for sidebar ────────────────────────────────────────────
    reg["add"]   = add_cust_dlg.open
    reg["reset"] = _reset_contacts

    # ── rebuild helpers ───────────────────────────────────────────────────────
    def _rebuild_customer_list():
        list_container = reg["list_container"]
        list_container.clear()
        dd = _load_yaml(path)
        with list_container:
            for cust_name in dd.get("customers", {}).keys():
                is_sel = selected["customer"] == cust_name
                bg = f"bg-{core.theme.get('toolbar_bg')}" if is_sel else ""
                with ui.element("div").classes(
                    f"w-full pl-7 pr-2 py-1.5 cursor-pointer flex items-center gap-1 "
                    f"hover:bg-slate-700 {bg}"
                ).on("click", lambda n=cust_name: _select_customer(n)):
                    ui.icon("person", size="xs").classes(
                        f"text-{core.theme.get('muted')} shrink-0"
                    )
                    ui.label(cust_name).classes("text-sm text-white truncate")

    reg["rebuild"] = _rebuild_customer_list

    def _select_customer(name: str):
        selected["customer"] = name
        if switch := reg.get("switch_to_contacts"):
            switch()
        _rebuild_customer_list()
        _reload_detail()

    def _reload_detail():
        detail_col.clear()
        customer = selected["customer"]
        if not customer:
            with detail_col:
                ui.label("Select a customer from the left panel to edit.").classes(
                    UI_STYLES.get_layout_classes("muted_text_sm")
                )
            return

        dd = _load_yaml(path)
        cdata = dd.get("customers", {}).get(customer, {})

        with detail_col:
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(customer).classes(
                    UI_STYLES.get_layout_classes("section_heading")
                )

                def _delete_customer(c=customer):
                    ddd = _load_yaml(path)
                    ddd.get("customers", {}).pop(c, None)
                    _save_yaml(path, ddd)
                    core.config_loader.reload_config("devops_contacts.yml")
                    selected["customer"] = None
                    _rebuild_customer_list()
                    _reload_detail()
                    ui.notify(f"Deleted '{c}'", type="warning")

                ui.button(icon="delete", on_click=_delete_customer).props(
                    "flat dense round color=negative"
                ).tooltip("Delete customer")

            for field_key, field_label, placeholder in [
                ("contacts",  "Contacts",          "name or email"),
                ("assignees", "Assignees (email)", "email@example.com"),
            ]:
                with ui.card().props("flat bordered").classes("w-full rounded-lg p-3"):
                    ui.label(field_label).classes(
                        f"text-sm font-semibold text-{core.theme.get('accent')} mb-2"
                    )
                    items = cdata.get(field_key, [])
                    with ui.row().classes("flex-wrap gap-2 mb-2"):
                        for item in items:
                            with ui.element("div").classes(
                                f"flex items-center bg-{core.theme.get('chip_bg')} "
                                "rounded-full px-3 py-1 gap-1"
                            ):
                                ui.label(item).classes("text-sm text-white")

                                def _remove(it=item, fk=field_key, c=customer):
                                    ddd = _load_yaml(path)
                                    lst = (
                                        ddd.get("customers", {})
                                        .get(c, {})
                                        .get(fk, [])
                                    )
                                    if it in lst:
                                        lst.remove(it)
                                    _save_yaml(path, ddd)
                                    core.config_loader.reload_config("devops_contacts.yml")
                                    _reload_detail()

                                ui.button(icon="close", on_click=_remove).props(
                                    "dense flat round size=xs color=negative"
                                )
                    if not items:
                        ui.label("None added yet.").classes(
                            UI_STYLES.get_layout_classes("muted_text_xs")
                        )
                    with ui.row().classes("items-center gap-2 mt-1"):
                        add_in = (
                            ui.input(placeholder).props("dense outlined").classes("flex-1")
                        )

                        def _add_item(fk=field_key, ai=add_in, c=customer):
                            v = (ai.value or "").strip()
                            if not v:
                                return
                            ddd = _load_yaml(path)
                            lst = (
                                ddd.setdefault("customers", {})
                                .setdefault(c, {})
                                .setdefault(fk, [])
                            )
                            if v not in lst:
                                lst.append(v)
                            _save_yaml(path, ddd)
                            core.config_loader.reload_config("devops_contacts.yml")
                            ai.value = ""
                            _reload_detail()

                        ui.button(icon="add", on_click=_add_item).props(
                            "dense flat color=primary"
                        )

            with ui.card().props("flat bordered").classes("w-full rounded-lg p-3"):
                ui.label("Default Assignee").classes(
                    f"text-sm font-semibold text-{core.theme.get('accent')} mb-2"
                )
                assignees = cdata.get("assignees", [])
                current_default = cdata.get("default_assignee", "")
                with ui.row().classes("items-center gap-2"):
                    default_sel = (
                        ui.select(assignees, label="Default Assignee", value=current_default)
                        .props("dense outlined")
                        .classes("flex-1")
                    )

                    def _save_default(c=customer):
                        ddd = _load_yaml(path)
                        ddd.setdefault("customers", {}).setdefault(c, {})[
                            "default_assignee"
                        ] = default_sel.value
                        _save_yaml(path, ddd)
                        core.config_loader.reload_config("devops_contacts.yml")
                        ui.notify("Default assignee saved", type="positive")

                    ui.button(icon="save", on_click=_save_default).props(
                        "color=primary dense flat"
                    ).tooltip("Save default")

    _rebuild_customer_list()
    _reload_detail()


# ─────────────────────────────────────────────────────────────────────────────
# DevOps Tags panel
# ─────────────────────────────────────────────────────────────────────────────


async def _render_devops_tags_tab(core: AppCore, reg: dict):
    path = _config_path(core, "devops_tags.yml")
    table_container = ui.element("div").classes("w-full")

    # ── Add / Edit dialog ─────────────────────────────────────────────────────
    with ui.dialog() as tag_dlg, ui.card().classes("w-96"):
        dlg_title = ui.label("Add Tag").classes("text-base font-bold mb-3")
        name_in = (
            ui.input("Name").props("outlined dense autofocus").classes("w-full mb-2")
        )
        with ui.row().classes("items-center gap-2 w-full mb-2"):
            icon_sel = (
                ui.select(ICON_SELECT_OPTIONS, label="Icon", value=_ICON_FIRST)
                .props("outlined dense")
                .classes("flex-1")
            )
            icon_preview = ui.icon(
                _ICON_FIRST, size="md"
            ).classes(f"text-{core.theme.get('accent')} self-center")

        custom_icon_in = (
            ui.input("Custom icon name", placeholder="e.g. rocket_launch")
            .props("outlined dense")
            .classes("w-full mb-2")
        )
        custom_icon_in.set_visibility(False)

        color_in = (
            ui.color_input(label="Colour", value="#b71c1c")
            .props("dense outlined")
            .classes("w-full mb-3")
        )

        def _on_icon_sel_change(e):
            if e.value == _ICON_CUSTOM:
                custom_icon_in.set_visibility(True)
                icon_preview.set_name(custom_icon_in.value or "help_outline")
            else:
                custom_icon_in.set_visibility(False)
                icon_preview.set_name(e.value or "help_outline")
            icon_preview.update()

        def _on_custom_icon_change(e):
            if icon_sel.value == _ICON_CUSTOM:
                icon_preview.set_name(e.value or "help_outline")
                icon_preview.update()

        icon_sel.on_value_change(_on_icon_sel_change)
        custom_icon_in.on_value_change(_on_custom_icon_change)

        with ui.row().classes("justify-end gap-2"):
            ui.button("Cancel", on_click=tag_dlg.close).props("flat dense")

            def _save_tag():
                name = (name_in.value or "").strip()
                if not name:
                    ui.notify("Name is required.", type="warning")
                    return
                icon = (
                    (custom_icon_in.value or "").strip()
                    if icon_sel.value == _ICON_CUSTOM
                    else icon_sel.value
                )
                color = (color_in.value or "").strip()
                d = _load_yaml(path)
                tags = d.setdefault("devops_tags", [])
                for t in tags:
                    if t.get("name") == name:
                        if icon:
                            t["icon"] = icon
                        if color:
                            t["color"] = color
                        break
                else:
                    entry: dict = {"name": name}
                    if icon:
                        entry["icon"] = icon
                    if color:
                        entry["color"] = color
                    tags.append(entry)
                _save_yaml(path, d)
                core.config_loader.reload_config("devops_tags.yml")
                ui.notify(f"Saved '{name}'", type="positive")
                tag_dlg.close()
                _reload_table()

            ui.button("Save", icon="save", on_click=_save_tag).props("color=primary dense")

    # ── dialog open helpers ───────────────────────────────────────────────────
    def _open_add():
        dlg_title.set_text("Add Tag")
        name_in.value = ""
        icon_sel.value = _ICON_FIRST
        custom_icon_in.value = ""
        custom_icon_in.set_visibility(False)
        color_in.value = "#b71c1c"
        icon_preview.set_name(_ICON_FIRST)
        icon_preview.update()
        tag_dlg.open()

    def _open_edit(tag: dict):
        dlg_title.set_text(f"Edit tag — {tag.get('name', '')}")
        name_in.value = tag.get("name", "")
        raw_icon = tag.get("icon", "")
        preset_values = [k for k in ICON_SELECT_OPTIONS if k != _ICON_CUSTOM]
        if raw_icon in preset_values:
            icon_sel.value = raw_icon
            custom_icon_in.value = ""
            custom_icon_in.set_visibility(False)
        else:
            icon_sel.value = _ICON_CUSTOM
            custom_icon_in.value = raw_icon
            custom_icon_in.set_visibility(True)
        icon_preview.set_name(raw_icon or "help_outline")
        icon_preview.update()
        color_in.value = tag.get("color", "#b71c1c")
        tag_dlg.open()

    # ── table rebuild ─────────────────────────────────────────────────────────
    def _reload_table():
        table_container.clear()
        data = _load_yaml(path)
        tags = data.get("devops_tags", [])
        with table_container:
            if not tags:
                ui.label("No tags yet — use Add Tag in the sidebar.").classes(
                    UI_STYLES.get_layout_classes("muted_text_sm")
                )
                return
            cols = [
                {"name": "name",    "label": "Name",    "field": "name",    "align": "left", "sortable": True},
                {"name": "icon",    "label": "Icon",    "field": "icon",    "align": "left"},
                {"name": "color",   "label": "Colour",  "field": "color",   "align": "left"},
                {"name": "actions", "label": "",        "field": "actions", "align": "center"},
            ]
            rows = [
                {"name": t.get("name", ""), "icon": t.get("icon", ""), "color": t.get("color", "")}
                for t in tags
            ]
            with ui.table(columns=cols, rows=rows, row_key="name").classes("w-full") as tbl:
                tbl.add_slot("body-cell-icon", """
                    <q-td :props="props">
                        <q-icon :name="props.value" size="sm" class="mr-2"/>
                        <span class="text-xs text-slate-400">{{ props.value }}</span>
                    </q-td>
                """)
                tbl.add_slot("body-cell-color", """
                    <q-td :props="props">
                        <q-badge :style="'background:' + props.value" :label="props.value"/>
                    </q-td>
                """)
                tbl.add_slot("body-cell-actions", """
                    <q-td :props="props" auto-width>
                        <q-btn flat dense round icon="edit" color="primary"
                               @click="$parent.$emit('edit', props.row)" class="mr-1"/>
                        <q-btn flat dense round icon="delete" color="negative"
                               @click="$parent.$emit('delete', props.row)"/>
                    </q-td>
                """)

                def on_edit(e):
                    _open_edit(e.args)

                def on_delete(e):
                    name = e.args.get("name", "")
                    d = _load_yaml(path)
                    d["devops_tags"] = [
                        t for t in d.get("devops_tags", []) if t.get("name") != name
                    ]
                    _save_yaml(path, d)
                    core.config_loader.reload_config("devops_tags.yml")
                    ui.notify(f"Deleted '{name}'", type="warning")
                    _reload_table()

                tbl.on("edit", on_edit)
                tbl.on("delete", on_delete)

    tags_template = path.parent / "devops_tags.yml.template"

    def _reset_tags():
        import shutil
        if tags_template.exists():
            shutil.copy2(tags_template, path)
            core.config_loader.reload_config("devops_tags.yml")
            _reload_table()
            ui.notify("Tags reset to defaults", type="warning")
        else:
            ui.notify("Template file not found", type="negative")

    # ── expose actions for sidebar ────────────────────────────────────────────
    reg["add"]   = _open_add
    reg["reset"] = _reset_tags

    # ── panel body ────────────────────────────────────────────────────────────
    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        _reload_table()


# ─────────────────────────────────────────────────────────────────────────────
# Theme panel
# ─────────────────────────────────────────────────────────────────────────────


async def _render_theme_tab(core: AppCore, reg: dict):
    theme_path = _config_path(core, "config_theme.yml")
    template_path = theme_path.parent / "config_theme.yml.template"
    data = _load_yaml(theme_path)
    colors = data.get("colors", {})

    PAIRED: list[tuple[str, str, str]] = [
        ("primary",   "accent",     "Primary / Accent"),
        ("secondary", "muted",      "Secondary / Muted"),
        ("dark",      "toolbar_bg", "Dark / Toolbar background"),
        ("dark_page", "nav_bg",     "Page / Nav background"),
    ]
    HEX_ONLY: list[tuple[str, str]] = [
        ("positive", "Positive"),
        ("negative", "Negative"),
        ("info",     "Info"),
        ("warning",  "Warning"),
    ]
    TOKEN_ONLY: list[tuple[str, str]] = [
        ("divider",  "Divider"),
        ("border",   "Border"),
        ("chip_bg",  "Chip background"),
    ]

    def _reset_theme():
        import shutil
        if template_path.exists():
            shutil.copy2(template_path, theme_path)
            core.config_loader.reload_config("config_theme.yml")
            ui.notify("Theme reset to defaults — refresh page (F5)", type="warning")
        else:
            ui.notify("Template file not found", type="negative")

    reg["reset"] = _reset_theme

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        ui.label(
            "Each colour picker saves both the hex value (for Quasar components) "
            "and the nearest Tailwind token (for class-based styling) simultaneously."
        ).classes(UI_STYLES.get_layout_classes("muted_text_xs") + " mb-3")

        all_inputs: dict = {}

        # ── Paired ────────────────────────────────────────────────────────────
        ui.label("Paired colours").classes(
            f"text-xs font-semibold text-{core.theme.get('muted')} mb-1"
        )
        with ui.grid(columns=2).classes("w-full gap-3 mb-4"):
            for hex_key, token_key, label in PAIRED:
                raw_hex   = colors.get(hex_key, "#000000")
                raw_token = colors.get(token_key, "slate-400")
                hex_val   = raw_hex if raw_hex.startswith("#") else _hex_of_token(raw_hex)
                token_holder: dict = {"value": raw_token}
                with ui.element("div").classes("flex flex-col gap-0"):
                    inp = (
                        ui.color_input(label=label, value=hex_val)
                        .props("dense outlined")
                        .classes("w-full")
                    )
                    with ui.row().classes("items-center gap-2 ml-0.5 mt-0.5"):
                        swatch = (
                            ui.element("div")
                            .classes("w-10 h-3.5 rounded shrink-0 border border-white/20")
                            .style(f"background-color: {hex_val}")
                        )
                        token_lbl = ui.label(raw_token).classes(
                            f"text-xs text-{core.theme.get('accent')}"
                        )

                    def _on_paired_change(e, tl=token_lbl, th=token_holder, sw=swatch):
                        t = _nearest_tailwind_token(e.value)
                        th["value"] = t
                        tl.set_text(t)
                        sw.style(f"background-color: {e.value}")

                    inp.on_value_change(_on_paired_change)
                all_inputs[hex_key]   = {"input": inp, "kind": "hex"}
                all_inputs[token_key] = {"kind": "token", "token_holder": token_holder}

        # ── Hex-only ──────────────────────────────────────────────────────────
        ui.label("Component colours").classes(
            f"text-xs font-semibold text-{core.theme.get('muted')} mb-1"
        )
        with ui.grid(columns=2).classes("w-full gap-3 mb-4"):
            for key, label in HEX_ONLY:
                val = colors.get(key, "#000000")
                with ui.element("div").classes("flex flex-col gap-0"):
                    inp = (
                        ui.color_input(label=label, value=val)
                        .props("dense outlined")
                        .classes("w-full")
                    )
                    swatch = (
                        ui.element("div")
                        .classes("w-10 h-3.5 rounded ml-0.5 mt-0.5 shrink-0 border border-white/20")
                        .style(f"background-color: {val}")
                    )

                    def _on_hex_change(e, sw=swatch):
                        sw.style(f"background-color: {e.value}")

                    inp.on_value_change(_on_hex_change)
                all_inputs[key] = {"input": inp, "kind": "hex"}

        # ── Token-only ────────────────────────────────────────────────────────
        ui.label("Additional tokens").classes(
            f"text-xs font-semibold text-{core.theme.get('muted')} mb-1"
        )
        with ui.grid(columns=2).classes("w-full gap-3"):
            for key, label in TOKEN_ONLY:
                raw_token = colors.get(key, "slate-400")
                hex_val   = _hex_of_token(raw_token)
                token_holder = {"value": raw_token}
                with ui.element("div").classes("flex flex-col gap-0"):
                    inp = (
                        ui.color_input(label=label, value=hex_val)
                        .props("dense outlined")
                        .classes("w-full")
                    )
                    with ui.row().classes("items-center gap-2 ml-0.5 mt-0.5"):
                        swatch = (
                            ui.element("div")
                            .classes("w-10 h-3.5 rounded shrink-0 border border-white/20")
                            .style(f"background-color: {hex_val}")
                        )
                        token_lbl = ui.label(raw_token).classes(
                            f"text-xs text-{core.theme.get('accent')}"
                        )

                    def _on_token_change(e, tl=token_lbl, th=token_holder, sw=swatch):
                        t = _nearest_tailwind_token(e.value)
                        th["value"] = t
                        tl.set_text(t)
                        sw.style(f"background-color: {e.value}")

                    inp.on_value_change(_on_token_change)
                all_inputs[key] = {"kind": "token", "input": inp, "token_holder": token_holder}

        def _save_theme():
            d = _load_yaml(theme_path)
            c = d.setdefault("colors", {})
            for k, meta in all_inputs.items():
                if meta["kind"] == "hex":
                    c[k] = meta["input"].value
                else:
                    c[k] = meta["token_holder"]["value"]
            _save_yaml(theme_path, d)
            core.config_loader.reload_config("config_theme.yml")
            ui.notify("Theme saved — refresh page to apply (F5)", type="positive")

        with ui.row().classes("gap-3 mt-4"):
            ui.button("Save Theme", icon="save", on_click=_save_theme).props("color=primary")


# ─────────────────────────────────────────────────────────────────────────────
# Page entry point
# ─────────────────────────────────────────────────────────────────────────────


async def settings_page():
    """Settings page — sidebar navigation with three configuration sections."""
    core = await AppCore.get_or_initialize()

    contacts_reg: dict = {}
    tags_reg:     dict = {}
    theme_reg:    dict = {}

    panel_refs: dict = {}
    row_refs:   dict = {}
    state = {"active": "contacts", "contacts_expanded": True}

    # These dicts hold element refs that are populated during sidebar render,
    # then used in _toggle_contacts / _switch which are called at click-time.
    _expand_icon: dict  = {}   # {"el": ui.icon}
    _sub_list:    dict  = {}   # {"el": ui.element}

    def _switch(section: str):
        state["active"] = section
        for k, panel in panel_refs.items():
            if k == section:
                panel.classes(remove="hidden")
            else:
                panel.classes("hidden")
        for k, row_el in row_refs.items():
            if k == section:
                row_el.classes("bg-slate-700", remove="hover:bg-slate-700")
            else:
                row_el.classes("hover:bg-slate-700", remove="bg-slate-700")

    def _toggle_contacts():
        if state["active"] != "contacts":
            # switching to contacts always expands
            _switch("contacts")
            state["contacts_expanded"] = True
            _sub_list["el"].classes(remove="hidden")
            _expand_icon["el"].set_name("expand_more")
        else:
            # already on contacts — toggle expand
            state["contacts_expanded"] = not state["contacts_expanded"]
            if state["contacts_expanded"]:
                _sub_list["el"].classes(remove="hidden")
                _expand_icon["el"].set_name("expand_more")
            else:
                _sub_list["el"].classes("hidden")
                _expand_icon["el"].set_name("chevron_right")

    from ..services.services import DevOpsService
    _svc = DevOpsService(core)
    _eng = core.devops_engine

    with toolbar(core.theme):
        ui.icon("tune", size="md").classes(f"text-{core.theme.get('accent')}")
        ui.label("Settings").classes(UI_STYLES.get_layout_classes("page_title"))

        ui.element("div").classes("flex-1")

        _sync_lbl = ui.label(
            f"incr: {_fmt_time(_eng.last_incremental_sync)}  ·  "
            f"full: {_fmt_time(_eng.last_full_sync)}"
        ).classes(UI_STYLES.get_layout_classes("muted_text_xs"))

        def _refresh_sync_labels():
            _sync_lbl.set_text(
                f"incr: {_fmt_time(_eng.last_incremental_sync)}  ·  "
                f"full: {_fmt_time(_eng.last_full_sync)}"
            )

        async def _run_incr():
            _svc.refresh_incremental_async()
            await asyncio.sleep(0.5)
            _refresh_sync_labels()

        async def _run_full():
            _svc.refresh_full_async()
            await asyncio.sleep(0.5)
            _refresh_sync_labels()

        ui.button("Incremental", icon="sync", on_click=_run_incr).props(
            "color=primary dense outline"
        )
        ui.button("Full Sync", icon="cloud_download", on_click=_run_full).props(
            "color=primary dense outline"
        )

    with page_card(scrollable=False):
        with ui.row().classes("w-full h-full gap-0 overflow-hidden"):

            # ── Left sidebar ──────────────────────────────────────────────────
            with ui.element("div").classes(
                "w-56 h-full flex flex-col shrink-0 py-1 overflow-y-auto"
            ).style("border-right: 1px solid #475569"):

                # ── CONTACTS (accordion row) ──────────────────────────────────
                with ui.row().classes(
                    "w-full items-center px-2 py-2.5 gap-1.5 cursor-pointer bg-slate-700"
                ).on("click", _toggle_contacts) as contacts_row:

                    exp_icon = ui.icon("expand_more", size="xs").classes(
                        f"text-{core.theme.get('accent')} shrink-0"
                    )
                    ui.icon("contacts", size="xs").classes(
                        f"text-{core.theme.get('muted')} shrink-0"
                    )
                    ui.label("DevOps Contacts").classes(
                        "text-sm text-white flex-1 truncate leading-tight"
                    )
                    with ui.row().classes("gap-0 shrink-0"):
                        ui.button(
                            icon="add",
                            on_click=lambda: contacts_reg.get("add") and contacts_reg["add"](),
                        ).props("flat dense round size=xs color=primary").tooltip("Add customer")
                        ui.button(
                            icon="restart_alt",
                            on_click=lambda: contacts_reg.get("reset") and contacts_reg["reset"](),
                        ).props("flat dense round size=xs color=primary").tooltip("Reset")

                row_refs["contacts"] = contacts_row
                _expand_icon["el"]   = exp_icon

                # ── customer sub-list ─────────────────────────────────────────
                contacts_sub = ui.element("div").classes("w-full")
                contacts_reg["list_container"] = contacts_sub
                _sub_list["el"] = contacts_sub

                ui.separator().classes("my-0.5 mx-3")

                # ── TAGS (plain row) ──────────────────────────────────────────
                with ui.row().classes(
                    "w-full items-center px-2 py-2.5 gap-1.5 cursor-pointer hover:bg-slate-700"
                ).on("click", lambda: _switch("tags")) as tags_row:
                    ui.icon("label", size="xs").classes(
                        f"text-{core.theme.get('muted')} shrink-0"
                    )
                    ui.label("DevOps Tags").classes(
                        "text-sm text-white flex-1 truncate leading-tight"
                    )
                    with ui.row().classes("gap-0 shrink-0"):
                        ui.button(
                            icon="add",
                            on_click=lambda: tags_reg.get("add") and tags_reg["add"](),
                        ).props("flat dense round size=xs color=primary").tooltip("Add tag")
                        ui.button(
                            icon="restart_alt",
                            on_click=lambda: tags_reg.get("reset") and tags_reg["reset"](),
                        ).props("flat dense round size=xs color=primary").tooltip("Reset")

                row_refs["tags"] = tags_row

                ui.separator().classes("my-0.5 mx-3")

                # ── THEME (plain row) ─────────────────────────────────────────
                with ui.row().classes(
                    "w-full items-center px-2 py-2.5 gap-1.5 cursor-pointer hover:bg-slate-700"
                ).on("click", lambda: _switch("theme")) as theme_row:
                    ui.icon("color_lens", size="xs").classes(
                        f"text-{core.theme.get('muted')} shrink-0"
                    )
                    ui.label("Theme").classes(
                        "text-sm text-white flex-1 truncate leading-tight"
                    )
                    with ui.row().classes("gap-0 shrink-0"):
                        ui.button(
                            icon="restart_alt",
                            on_click=lambda: theme_reg.get("reset") and theme_reg["reset"](),
                        ).props("flat dense round size=xs color=primary").tooltip("Reset")

                row_refs["theme"] = theme_row

            # ── Right panels (pre-rendered, toggled via hidden class) ─────────
            with ui.element("div").classes("flex-1 h-full overflow-hidden relative"):

                # Contacts — active by default
                with ui.element("div").classes("absolute inset-0") as p:
                    await _render_devops_contacts_tab(core, contacts_reg)
                panel_refs["contacts"] = p

                # Tags
                with ui.element("div").classes("absolute inset-0 hidden") as p:
                    with ui.scroll_area().classes("w-full h-full"):
                        with ui.column().classes("w-full gap-4 p-4"):
                            await _render_devops_tags_tab(core, tags_reg)
                panel_refs["tags"] = p

                # Theme
                with ui.element("div").classes("absolute inset-0 hidden") as p:
                    with ui.scroll_area().classes("w-full h-full"):
                        with ui.column().classes("w-full gap-4 p-4"):
                            await _render_theme_tab(core, theme_reg)
                panel_refs["theme"] = p

    # wire switch callback so customer clicks work from any panel
    contacts_reg["switch_to_contacts"] = lambda: _switch("contacts")
    # populate the sidebar customer list after all panels are rendered
    if contacts_reg.get("rebuild"):
        contacts_reg["rebuild"]()
