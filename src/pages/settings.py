"""
Settings Page

Toolbar-tab layout (the app's standard idiom) with four sections:
  - DevOps  (sync controls + per-customer contacts/assignees)
  - Tags    (work-item tag table + add/edit dialog)
  - Theme   (colour pickers for the app palette)
  - Data    (database backup, time & billing defaults, about/version)

Each section renders as cards with a consistent accent header; per-section
actions (Add / Reset / Save) live inside the section they affect.
"""

from pathlib import Path
from datetime import datetime
import asyncio
import os
import re
import shutil
import tempfile
import yaml
from nicegui import app, ui
from ..core.app import AppCore
from ..ui.elements import toolbar, toolbar_group
from ..helpers import UI_STYLES


def _prune_backups(backups_dir: Path, keep: int = 10) -> None:
    """Keep only the newest `keep` worktimer_*.db backups; delete the rest."""
    files = sorted(
        backups_dir.glob("worktimer_*.db"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def _render_backup_card(core) -> None:
    """Database backup as a Settings card: back up to the local backups/ folder
    (auto-synced via OneDrive) or download a copy. SQLite online backup, safe live."""
    backups_dir = Path(core.settings.db_path).resolve().parent.parent / "backups"
    muted = UI_STYLES.get_layout_classes("muted_text")

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        ui.label("Database backup").classes(
            f"text-sm font-semibold text-{core.theme.get('accent')}"
        )
        ui.label(
            "Consistent copies, safe while the app runs. Saved to a backups/ "
            "folder next to the database; the newest 10 are kept."
        ).classes("text-xs " + muted)

        list_col = ui.column().classes("w-full gap-0 mt-2 max-h-60 overflow-auto")

        def _refresh():
            list_col.clear()
            files = (
                sorted(backups_dir.glob("worktimer_*.db"), reverse=True)
                if backups_dir.exists()
                else []
            )
            with list_col:
                if not files:
                    ui.label("No backups yet.").classes("text-sm " + muted)
                for f in files[:10]:
                    kb = f.stat().st_size / 1024
                    ui.label(f"{f.name}  ·  {kb:,.0f} KB").classes("text-xs " + muted)

        async def _backup_now():
            try:
                backups_dir.mkdir(parents=True, exist_ok=True)
                dest = backups_dir / f"worktimer_{datetime.now():%Y-%m-%d_%H%M%S}.db"
                await asyncio.to_thread(core.query_engine.db.backup_to, str(dest))
                _prune_backups(backups_dir, keep=10)
                ui.notify(f"Backup saved: backups/{dest.name}", type="positive")
                _refresh()
            except Exception as ex:
                core.logger.error(f"Backup failed: {ex}")
                ui.notify(f"Backup failed: {ex}", type="negative")

        async def _download():
            tmp = None
            try:
                fd, tmp = tempfile.mkstemp(suffix=".db")
                os.close(fd)
                await asyncio.to_thread(core.query_engine.db.backup_to, tmp)
                data = Path(tmp).read_bytes()
                ui.download(data, f"worktimer_backup_{datetime.now():%Y-%m-%d_%H%M}.db")
            except Exception as ex:
                core.logger.error(f"Export failed: {ex}")
                ui.notify(f"Export failed: {ex}", type="negative")
            finally:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)

        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("Download", icon="download", on_click=_download).props(
                "outline color=primary no-caps dense"
            ).tooltip("Save a copy via your browser's download")
            ui.button("Backup now", icon="save", on_click=_backup_now).props(
                "color=primary no-caps dense"
            ).tooltip("Save a copy to the backups/ folder next to the database")

        _refresh()

def _render_tracker_defaults_card(core) -> None:
    """Per-tracker prefills for the add-work-item form (state, priority,
    initial column, source, contact). Saved to config/tracker_defaults.yml;
    the add dialog reads the file fresh, so changes apply immediately."""
    from ..tracker_defaults import (
        ALL_TYPES,
        load_tracker_defaults,
        save_tracker_defaults,
    )
    from ..trackers.registry import get_provider_class
    from ..ui.work_item_handlers import WorkItemHandlers

    muted = UI_STYLES.get_layout_classes("muted_text")
    try:
        tdf = core.query_engine.db.fetch_query(
            "select tracker_name, coalesce(integration_type,'devops') as itype "
            "from trackers order by tracker_name"
        )
        trackers = (
            dict(zip(tdf["tracker_name"], tdf["itype"])) if not tdf.empty else {}
        )
        cust_map = core.query_engine.db.get_customer_tracker_names()
    except Exception:
        trackers, cust_map = {}, {}

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        ui.label("Work-item form defaults").classes(
            f"text-sm font-semibold text-{core.theme.get('accent')}"
        )
        ui.label(
            "Prefills for new work items, per tracker AND work-item type — "
            "'All types' applies everywhere, a specific type overrides it "
            "per field. Fields a tracker or level doesn't use are ignored "
            "(for Jira, state IS the board column, so no column default)."
        ).classes("text-xs " + muted + " mb-2")

        if not trackers:
            ui.label("No trackers configured yet.").classes("text-xs " + muted)
            return

        stored = load_tracker_defaults(core.config_loader.config_folder)
        src_field = next(
            (
                f
                for f in core.ui_config.get("board_devops_forms", {})
                .get("add", {})
                .get("fields", [])
                if f.get("name") == "source"
            ),
            {},
        )
        source_options = list(src_field.get("options") or [])

        def _tracker_customers(tname):
            return [c for c, t in cust_map.items() if t == tname]

        def _tracker_levels(tname):
            cls = get_provider_class(trackers.get(tname) or "devops")
            levels = list(cls.type_hierarchy()) if cls else []
            return {ALL_TYPES: "All types", **{lv: lv for lv in levels}}

        with ui.row().classes("w-full gap-3 flex-wrap"):
            tracker_sel = ui.select(
                list(trackers), label="Tracker", value=next(iter(trackers))
            ).props("dense outlined").classes("w-64")
            type_sel = ui.select(
                _tracker_levels(next(iter(trackers))),
                label="Work item type", value=ALL_TYPES,
            ).props("dense outlined").classes("w-44")

        with ui.row().classes("w-full gap-3 flex-wrap"):
            state_in = ui.select(
                [], label="State", with_input=True, new_value_mode="add-unique"
            ).props("dense outlined clearable").classes("w-44")
            prio_in = ui.select(
                [1, 2, 3, 4], label="Priority"
            ).props("dense outlined clearable").classes("w-32")
            col_in = ui.select(
                [], label="Initial board column", with_input=True,
                new_value_mode="add-unique",
            ).props("dense outlined clearable").classes("w-52")
            source_in = ui.select(
                source_options, label="Source", with_input=True,
                new_value_mode="add-unique",
            ).props("dense outlined clearable").classes("w-40")
            contact_in = ui.input(label="Contact person").props(
                "dense outlined clearable"
            ).classes("w-52")

        def _load_for(tname, wtype):
            vals = (stored.get(tname) or {}).get(wtype) or {}
            # Options from a live customer on this tracker, when one exists.
            # Board columns are per work-item type where the cache has them.
            states, columns = [], []
            eng = core.tracker_engine
            for cust in _tracker_customers(tname):
                if eng is not None:
                    try:
                        states = eng.state_options(cust)
                    except Exception:
                        states = []
                cols_by_type = WorkItemHandlers.devops_columns_cache.get(
                    cust, {}
                )
                if wtype != ALL_TYPES and cols_by_type.get(wtype):
                    columns = list(cols_by_type[wtype])
                else:
                    columns = sorted(
                        {c for lst in cols_by_type.values() for c in lst}
                    )
                if states or columns:
                    break
            state_in.set_options(states or [], value=vals.get("state"))
            prio_in.value = vals.get("priority")
            is_jira = trackers.get(tname) == "jira"
            col_in.set_visibility(not is_jira)
            col_in.set_options(columns or [], value=(
                None if is_jira else vals.get("board_column")
            ))
            source_in.value = vals.get("source")
            contact_in.value = vals.get("contact_person") or ""

        def _save():
            tname = tracker_sel.value
            wtype = type_sel.value or ALL_TYPES
            if not tname:
                return
            vals = {
                "state": state_in.value or None,
                "priority": int(prio_in.value) if prio_in.value else None,
                "board_column": (
                    col_in.value or None
                    if trackers.get(tname) != "jira"
                    else None
                ),
                "source": source_in.value or None,
                "contact_person": (contact_in.value or "").strip() or None,
            }
            vals = {k: v for k, v in vals.items() if v is not None}
            entry = stored.setdefault(tname, {})
            if vals:
                entry[wtype] = vals
            else:
                entry.pop(wtype, None)
            if not entry:
                stored.pop(tname, None)
            try:
                save_tracker_defaults(core.config_loader.config_folder, stored)
                level = "all types" if wtype == ALL_TYPES else wtype
                ui.notify(
                    f"Defaults saved for '{tname}' ({level})", type="positive"
                )
            except Exception as ex:
                core.logger.error(f"Saving tracker defaults failed: {ex}")
                ui.notify(f"Save failed: {ex}", type="negative")

        def _on_tracker_change(e):
            type_sel.set_options(_tracker_levels(e.value), value=ALL_TYPES)
            _load_for(e.value, ALL_TYPES)

        tracker_sel.on_value_change(_on_tracker_change)
        type_sel.on_value_change(
            lambda e: _load_for(tracker_sel.value, e.value or ALL_TYPES)
        )
        _load_for(tracker_sel.value, ALL_TYPES)

        with ui.row().classes("w-full justify-end mt-2"):
            ui.button("Save", icon="save", on_click=_save).props(
                "color=primary no-caps dense"
            )


def _render_time_settings_card(core) -> None:
    """Edit the global time/billing defaults (the config's time_settings block).

    Saved to config/time_settings.yml — a small override file merged over
    config_ui.yml at load — so the commented main config is never rewritten."""
    ts = dict(core.ui_config.get("time_settings") or {})
    muted = UI_STYLES.get_layout_classes("muted_text")

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        ui.label("Time & billing defaults").classes(
            f"text-sm font-semibold text-{core.theme.get('accent')}"
        )
        ui.label(
            "Global defaults used by Reports — a customer's own expected % "
            "overrides the target where set."
        ).classes("text-xs " + muted + " mb-2")

        with ui.row().classes("w-full gap-3 flex-wrap"):
            round_in = ui.number(
                label="Default rounding (min)", min=0, step=5,
                value=int(ts.get("rounding_minutes", 0) or 0),
            ).props("dense outlined").classes("w-44")
            mode_in = ui.select(
                ["up", "nearest", "down"], label="Rounding mode",
                value=str(ts.get("rounding_mode", "up") or "up"),
            ).props("dense outlined").classes("w-36")
            currency_in = ui.input(
                label="Currency suffix", value=str(ts.get("currency", "") or ""),
            ).props("dense outlined").classes("w-32")
            hours_in = ui.number(
                label="Target hours/day", min=0, step=0.5,
                value=float(ts.get("target_hours_per_day", 8) or 8),
            ).props("dense outlined").classes("w-36")
            pct_in = ui.number(
                label="Target %", min=0, step=5,
                value=float(ts.get("target_percent", 100) or 100),
            ).props("dense outlined").classes("w-32")

        def _save():
            values = {
                "rounding_minutes": int(round_in.value or 0),
                "rounding_mode": str(mode_in.value or "up"),
                "currency": str(currency_in.value or ""),
                "target_hours_per_day": float(hours_in.value or 8),
                "target_percent": float(pct_in.value or 100),
            }
            try:
                _save_yaml(_config_path(core, "time_settings.yml"), values)
                # Live for this session too — Reports reads core.ui_config.
                core.ui_config["time_settings"] = values
                ui.notify("Time & billing defaults saved", type="positive")
            except Exception as ex:
                core.logger.error(f"Saving time settings failed: {ex}")
                ui.notify(f"Save failed: {ex}", type="negative")

        with ui.row().classes("w-full justify-end mt-2"):
            ui.button("Save", icon="save", on_click=_save).props(
                "color=primary no-caps dense"
            )


async def _render_about_card(core) -> None:
    """App version + update status (reuses the cached daily update check)."""
    from ..services.update_checker import _current_version, check_for_update

    muted = UI_STYLES.get_layout_classes("muted_text")
    version = _current_version()
    status_txt, status_icon, status_cls = "Update check unavailable", "help", muted
    try:
        result = await check_for_update()
        if result.get("available"):
            status_txt = f"v{result['latest']} available — update with git pull"
            status_icon, status_cls = "upgrade", "text-amber-400"
        else:
            status_txt = "Up to date"
            status_icon, status_cls = "check_circle", "text-green-500"
    except Exception:
        pass

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        ui.label("About").classes(
            f"text-sm font-semibold text-{core.theme.get('accent')}"
        )
        with ui.row().classes("items-center gap-2 mt-1"):
            ui.label(f"WorkTimer v{version}").classes("text-sm text-white")
            ui.icon(status_icon, size="xs").classes(f"{status_cls} shrink-0")
            ui.label(status_txt).classes("text-xs " + muted)


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


async def _confirm_reset(what: str) -> bool:
    """Confirm dialog for the destructive reset-to-template actions."""
    with ui.dialog() as dlg, ui.card().classes("w-96"):
        ui.label(f"Reset {what} to defaults?").classes("text-sm font-semibold")
        ui.label("Your current configuration will be overwritten with the template.").classes(
            UI_STYLES.get_layout_classes("muted_text_xs")
        )
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=lambda: dlg.submit(False)).props("flat")
            ui.button("Reset", on_click=lambda: dlg.submit(True)).props("color=negative")
    return await dlg


# ─────────────────────────────────────────────────────────────────────────────
# DevOps Contacts panel
# ─────────────────────────────────────────────────────────────────────────────


def _render_description_templates_card(core) -> None:
    """Per-level description templates for the add-work-item form (the
    markdown scaffold preloaded into a new Epic / Feature / User Story / …).
    Saved to config/description_templates.yml — merged over config_ui.yml at
    load, so the commented main config file is never rewritten."""
    from ..trackers.registry import available_providers, get_provider_class

    muted = UI_STYLES.get_layout_classes("muted_text")
    override_path = _config_path(core, "description_templates.yml")

    def _live_field() -> dict:
        for f in (
            core.ui_config.get("board_devops_forms", {}).get("add", {}).get("fields")
            or []
        ):
            if isinstance(f, dict) and f.get("name") == "description_editor":
                return f
        return {}

    current = dict(_live_field().get("templates") or {})

    # Levels: the union of every registered tracker's hierarchy, plus any
    # extra keys already carrying a template.
    levels: list[str] = []
    for pkey in available_providers():
        try:
            for t in get_provider_class(pkey).type_hierarchy():
                if t not in levels:
                    levels.append(t)
        except Exception:
            pass
    for k in current:
        if k not in levels:
            levels.append(k)
    if not levels:
        levels = ["Epic", "Feature", "User Story"]

    drafts: dict = {}
    sel = {"level": levels[0]}

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        ui.label("Description templates").classes(
            f"text-sm font-semibold text-{core.theme.get('accent')}"
        )
        ui.label(
            "The markdown scaffold preloaded into a new work item's description, "
            "per level. Placeholders: {{today}} inserts the creation date; "
            "{{source}} and {{contact_person}} (alias {{contact}}) stay in sync "
            "with the form's dropdowns — the line carrying the placeholder is "
            "rewritten on change, so keep some label text on it (e.g. "
            '"**Source:** {{source}}"). Applies to newly opened add dialogs.'
        ).classes("text-xs " + muted + " mb-2")

        with ui.row().classes("w-full items-center gap-2"):
            level_sel = ui.select(
                levels, value=sel["level"], label="Level",
            ).props("dense outlined options-dense").classes("w-48")
            ui.space()
            save_btn = ui.button("Save", icon="save").props(
                "color=primary no-caps dense"
            )
            reset_btn = ui.button("Reset level", icon="restart_alt").props(
                "flat dense color=primary no-caps"
            )
            reset_btn.tooltip("Restore this level's shipped template")

        editor = (
            ui.codemirror(
                current.get(sel["level"], ""), language="Markdown", theme="dracula"
            )
            .classes("w-full mt-2")
            .style("height: 280px;")
        )

        def _on_level(e):
            # Stash the unsaved edit so switching levels loses nothing.
            drafts[sel["level"]] = editor.value
            sel["level"] = e.value
            editor.value = drafts.get(e.value, current.get(e.value, ""))

        level_sel.on_value_change(_on_level)

        def _save():
            drafts[sel["level"]] = editor.value
            try:
                data = _load_yaml(override_path)
                tpl = dict(data.get("templates") or {})
                tpl.update({k: str(v or "") for k, v in drafts.items()})
                data["templates"] = tpl
                _save_yaml(override_path, data)
                live = _live_field()
                if live:
                    live["templates"] = {**(live.get("templates") or {}), **tpl}
                current.update(tpl)
                # Future clients read the loader's config — remerge it.
                core.config_loader.reload_config("config_ui.yml")
                ui.notify(
                    "Templates saved — applies to newly opened work-item dialogs",
                    type="positive",
                )
            except Exception as ex:
                core.logger.error(f"Saving description templates failed: {ex}")
                ui.notify(f"Save failed: {ex}", type="negative")

        save_btn.on("click", _save)

        # NOTE: async handlers bound to the click keep the slot context, so
        # _confirm_reset can build its dialog — a bare asyncio.create_task
        # has no slot stack and crashes ui.dialog().
        async def _reset():
            lvl = sel["level"]
            if not await _confirm_reset(f"the {lvl} template"):
                return
            try:
                # Shipped default straight from the pristine config_ui.yml.
                shipped: dict = {}
                raw = _load_yaml(_config_path(core, "config_ui.yml"))
                for f in (
                    ((raw.get("board_devops_forms") or {}).get("add") or {})
                    .get("fields") or []
                ):
                    if isinstance(f, dict) and f.get("name") == "description_editor":
                        shipped = dict(f.get("templates") or {})
                        break
                data = _load_yaml(override_path)
                tpl = dict(data.get("templates") or {})
                tpl.pop(lvl, None)
                data["templates"] = tpl
                _save_yaml(override_path, data)
                default_val = shipped.get(lvl, "")
                live = _live_field()
                if live:
                    live_tpl = dict(live.get("templates") or {})
                    if default_val:
                        live_tpl[lvl] = default_val
                    else:
                        live_tpl.pop(lvl, None)
                    live["templates"] = live_tpl
                if default_val:
                    current[lvl] = default_val
                else:
                    current.pop(lvl, None)
                drafts.pop(lvl, None)
                editor.value = default_val
                core.config_loader.reload_config("config_ui.yml")
                ui.notify(f"{lvl} template reset to default", type="warning")
            except Exception as ex:
                core.logger.error(f"Resetting template failed: {ex}")
                ui.notify(f"Reset failed: {ex}", type="negative")

        reset_btn.on("click", _reset)


async def _render_devops_contacts_tab(core: AppCore):
    """DevOps contacts editor — in-panel customer selector + per-customer detail."""
    path = _config_path(core, "devops_contacts.yml")
    selected: dict = {"customer": None}
    contacts_template = path.parent / "devops_contacts.yml.template"

    # Async click handler (not a bare asyncio task): NiceGUI keeps the slot
    # context for awaited handlers, which _confirm_reset's dialog needs.
    async def _reset_contacts():
        if not contacts_template.exists():
            ui.notify("Template file not found", type="negative")
            return
        if not await _confirm_reset("DevOps contacts"):
            return
        shutil.copy2(contacts_template, path)
        core.config_loader.reload_config("devops_contacts.yml")
        selected["customer"] = None
        _refresh_customer_select()
        _reload_detail()
        ui.notify("Contacts reset to defaults", type="warning")

    # ── header: customer selector + actions (the panel provides scrolling) ────
    def _on_select(e):
        if e.value and e.value != selected["customer"]:
            selected["customer"] = e.value
            _reload_detail()

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-3"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            cust_select = (
                ui.select([], label="Customer", on_change=_on_select)
                .props("dense outlined")
                .classes("flex-1")
            )
            ui.button(
                "Add customer", icon="add",
                on_click=lambda: add_cust_dlg.open(),
            ).props("outline color=primary no-caps dense")
            ui.button(icon="restart_alt", on_click=_reset_contacts).props(
                "flat dense color=primary"
            ).tooltip("Reset contacts to the template")

    detail_col = ui.column().classes("w-full gap-4")

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
                _refresh_customer_select()
                _reload_detail()
                ui.notify(f"Customer '{name}' added", type="positive")

            ui.button("Add", icon="add", on_click=_do_add_customer).props(
                "color=primary dense"
            )

    # ── rebuild helpers ───────────────────────────────────────────────────────
    def _refresh_customer_select():
        dd = _load_yaml(path)
        names = list(dd.get("customers", {}).keys())
        if selected["customer"] not in names:
            selected["customer"] = names[0] if names else None
        cust_select.set_options(names, value=selected["customer"])

    def _reload_detail():
        detail_col.clear()
        customer = selected["customer"]
        if not customer:
            with detail_col:
                ui.label("No customers yet — use Add customer above.").classes(
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
                    _refresh_customer_select()
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

                        if field_key == "assignees":

                            async def _fetch_members(c=customer):
                                """Pull the tracker's member list and let the
                                user tick whom to import as assignees."""
                                eng = core.tracker_engine
                                manager = (
                                    getattr(eng, "manager", None) if eng else None
                                )
                                if manager is None or c not in getattr(
                                    manager, "clients", {}
                                ):
                                    ui.notify(
                                        "No live tracker connection for "
                                        "this customer",
                                        type="warning",
                                    )
                                    return
                                ok, res = await asyncio.to_thread(
                                    manager.list_members, c
                                )
                                if not ok:
                                    ui.notify(
                                        f"Fetch failed: {res}", type="negative"
                                    )
                                    return
                                if not res:
                                    ui.notify("No members found", type="info")
                                    return
                                existing = set(
                                    (
                                        _load_yaml(path)
                                        .get("customers", {})
                                        .get(c, {}) or {}
                                    ).get("assignees") or []
                                )
                                with ui.dialog() as mdlg, ui.card().classes(
                                    "rounded-lg"
                                ).style("min-width: 380px; max-width: 90vw;"):
                                    ui.label(
                                        f"Tracker members — {c}"
                                    ).classes("text-sm font-semibold")
                                    ui.label(
                                        "Tick whom to add to the assignee "
                                        "list (already-added are locked)."
                                    ).classes(
                                        UI_STYLES.get_layout_classes(
                                            "muted_text_xs"
                                        )
                                    )
                                    boxes = {}
                                    with ui.column().classes(
                                        "gap-0 mt-2 w-full"
                                    ).style(
                                        "max-height: 50vh; overflow-y: auto;"
                                    ):
                                        for name in res:
                                            already = name in existing
                                            cb = ui.checkbox(
                                                name, value=already
                                            ).props("dense")
                                            if already:
                                                cb.props("disable")
                                            boxes[name] = (cb, already)

                                    def _import():
                                        ddd = _load_yaml(path)
                                        lst = (
                                            ddd.setdefault("customers", {})
                                            .setdefault(c, {})
                                            .setdefault("assignees", [])
                                        )
                                        added = 0
                                        for nm, (cb, already) in boxes.items():
                                            if (
                                                cb.value
                                                and not already
                                                and nm not in lst
                                            ):
                                                lst.append(nm)
                                                added += 1
                                        _save_yaml(path, ddd)
                                        core.config_loader.reload_config(
                                            "devops_contacts.yml"
                                        )
                                        mdlg.close()
                                        _reload_detail()
                                        ui.notify(
                                            f"Imported {added} member(s)",
                                            type="positive",
                                        )

                                    with ui.row().classes(
                                        "w-full justify-end gap-2 mt-2"
                                    ):
                                        ui.button(
                                            "Cancel", on_click=mdlg.close
                                        ).props("flat")
                                        ui.button(
                                            "Import selected",
                                            icon="download",
                                            on_click=_import,
                                        ).props("color=primary")
                                mdlg.on("hide", lambda: mdlg.delete())
                                mdlg.open()

                            ui.button(
                                icon="cloud_download", on_click=_fetch_members
                            ).props("dense flat color=primary").tooltip(
                                "Fetch members from the tracker"
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

    _refresh_customer_select()
    _reload_detail()


# ─────────────────────────────────────────────────────────────────────────────
# DevOps Tags panel
# ─────────────────────────────────────────────────────────────────────────────


async def _render_devops_tags_tab(core: AppCore):
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
                ui.label("No tags yet — use Add tag above.").classes(
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

    # Async click handler (not a bare asyncio task): NiceGUI keeps the slot
    # context for awaited handlers, which _confirm_reset's dialog needs.
    async def _reset_tags():
        if not tags_template.exists():
            ui.notify("Template file not found", type="negative")
            return
        if not await _confirm_reset("DevOps tags"):
            return
        shutil.copy2(tags_template, path)
        core.config_loader.reload_config("devops_tags.yml")
        _reload_table()
        ui.notify("Tags reset to defaults", type="warning")

    # ── panel body ────────────────────────────────────────────────────────────
    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        with ui.row().classes("w-full items-center justify-between mb-2"):
            ui.label("Work-item tags").classes(
                f"text-sm font-semibold text-{core.theme.get('accent')}"
            )
            with ui.row().classes("gap-1 shrink-0"):
                ui.button("Add tag", icon="add", on_click=_open_add).props(
                    "outline color=primary no-caps dense"
                )
                ui.button(icon="restart_alt", on_click=_reset_tags).props(
                    "flat dense color=primary"
                ).tooltip("Reset tags to the template")
        _reload_table()


# ─────────────────────────────────────────────────────────────────────────────
# Theme panel
# ─────────────────────────────────────────────────────────────────────────────


async def _render_theme_tab(core: AppCore):
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

    # Async click handler (not a bare asyncio task): NiceGUI keeps the slot
    # context for awaited handlers, which _confirm_reset's dialog needs.
    async def _reset_theme():
        if not template_path.exists():
            ui.notify("Template file not found", type="negative")
            return
        if not await _confirm_reset("the theme"):
            return
        shutil.copy2(template_path, theme_path)
        core.config_loader.reload_config("config_theme.yml")
        # Ctrl+R, not F5 — F5 is intentionally suppressed app-wide (query editor
        # binds it to Execute), so don't advise a shortcut that won't work.
        ui.notify("Theme reset to defaults — reload the page (Ctrl+R) to apply", type="warning")

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        with ui.row().classes("w-full items-center justify-between mb-1"):
            ui.label("Theme colours").classes(
                f"text-sm font-semibold text-{core.theme.get('accent')}"
            )
            ui.button(icon="restart_alt", on_click=_reset_theme).props(
                "flat dense color=primary"
            ).tooltip("Reset theme to the template")
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
            # Apply the Quasar palette live; class-based (Tailwind) colours still
            # need a page reload. Ctrl+R, not F5 — F5 is suppressed app-wide.
            core.theme = core.config_loader.get_raw_dict("theme")
            core.apply_theme()
            ui.notify(
                "Theme saved — colours applied, reload the page (Ctrl+R) for full effect",
                type="positive",
            )

        with ui.row().classes("gap-3 mt-4"):
            ui.button("Save Theme", icon="save", on_click=_save_theme).props("color=primary")

    # ── Query-editor skin ─────────────────────────────────────────────────────
    # Per-user (app.storage.user), unlike the app palette above which is shared —
    # each person picks their own editor colours. The Query Editor reads the
    # value on every page render, so it applies on the next visit.
    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        ui.label("Query editor skin").classes(
            f"text-sm font-semibold text-{core.theme.get('accent')}"
        )
        ui.label(
            "Colour scheme for the SQL editor on the Query Editor page. "
            "Saved per user; the preview below applies immediately."
        ).classes("text-xs opacity-70 mb-2")

        current = str(app.storage.user.get("query_editor_theme", "dracula"))
        with ui.row().classes("w-full items-start gap-4"):
            preview = (
                ui.codemirror(
                    "select customer_name,\n"
                    "       round(sum(cost), 2) as amount\n"
                    "from time_entries\n"
                    "group by customer_name\n"
                    "order by amount desc;",
                    language="SQLite",
                )
                .classes("flex-1")
                .style("height: 150px; min-width: 16rem;")
            )
            # The *Style entries are highlight-style internals, not full skins.
            names = sorted(
                (t for t in preview.supported_themes if not t.endswith("Style")),
                key=str.lower,
            )
            if current in names:
                preview.set_theme(current)
            else:
                current = "dracula"

            def _pretty(name: str) -> str:
                label = re.sub(r"(?<!^)(?=[A-Z])", " ", name).title()
                return label.replace("Vscode", "VS Code").replace("Bbedit", "BBEdit")

            def _on_skin(e):
                skin = e.value or "dracula"
                app.storage.user["query_editor_theme"] = skin
                preview.set_theme(skin)

            ui.select(
                {n: _pretty(n) for n in names},
                value=current,
                label="Skin",
                on_change=_on_skin,
            ).props("outlined dense options-dense").classes("w-56")


# ─────────────────────────────────────────────────────────────────────────────
# Page entry point
# ─────────────────────────────────────────────────────────────────────────────


async def settings_page():
    """Settings page — toolbar tabs with four sections (DevOps / Tags / Theme / Data),
    matching the navigation idiom of the Data Input and Documentation pages."""
    core = await AppCore.get_or_initialize()

    from ..services.services import TrackerSyncService
    _svc = TrackerSyncService(core)
    # May be None when DevOps init was skipped (no PAT customers / no internet) —
    # the page must still render, just without the sync controls.
    _eng = core.tracker_engine

    with toolbar(core.theme):
        with toolbar_group(core.theme, divider_after=True):
            ui.icon("tune", size="md").classes(f"text-{core.theme.get('accent')}")
            ui.label("Settings").classes(UI_STYLES.get_layout_classes("page_title"))

        with (
            ui.tabs(value="devops")
            .props(
                f'horizontal dense active-color="{core.theme.get("accent")}" '
                f'indicator-color="{core.theme.get("accent")}"'
            )
            .classes(UI_STYLES.get_layout_classes("tab_label"))
        ) as main_tabs:
            ui.tab("devops", label="Trackers", icon="cloud_sync")
            ui.tab("tags", label="Tags", icon="label")
            ui.tab("theme", label="Theme", icon="color_lens")
            ui.tab("data", label="Data", icon="storage")

    def _render_sync_card():
        """DevOps sync controls — moved out of the toolbar into the section."""
        with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
            ui.label("Synchronisation").classes(
                f"text-sm font-semibold text-{core.theme.get('accent')}"
            )
            if _eng is None:
                ui.label(
                    "No tracker configured — add a customer with a PAT token and "
                    "org URL to enable syncing."
                ).classes(UI_STYLES.get_layout_classes("muted_text_xs") + " mt-1")
                return

            with ui.row().classes("w-full items-center gap-3 no-wrap mt-1"):
                _sync_lbl = ui.label(
                    f"incr: {_fmt_time(_eng.last_incremental_sync)}  ·  "
                    f"full: {_fmt_time(_eng.last_full_sync)}"
                ).classes(UI_STYLES.get_layout_classes("muted_text_xs") + " flex-1")

                def _refresh_sync_labels():
                    try:
                        _sync_lbl.set_text(
                            f"incr: {_fmt_time(_eng.last_incremental_sync)}  ·  "
                            f"full: {_fmt_time(_eng.last_full_sync)}"
                        )
                    except Exception:
                        pass  # user navigated away while the sync was running

                async def _run_incr():
                    await _svc.refresh_incremental()
                    _refresh_sync_labels()

                async def _run_full():
                    await _svc.refresh_full()
                    _refresh_sync_labels()

                ui.button("Incremental", icon="sync", on_click=_run_incr).props(
                    "color=primary dense outline no-caps"
                )
                ui.button("Full Sync", icon="cloud_download", on_click=_run_full).props(
                    "color=primary dense outline no-caps"
                )

    with (
        ui.tab_panels(main_tabs, value="devops")
        .props("vertical")
        .classes("wt-page-content w-full")
        .style("background: transparent;")
    ):
        with ui.tab_panel("devops").classes("p-0 h-full"):
            with ui.scroll_area().classes("w-full h-full"):
                with ui.column().classes("w-full gap-4 p-4"):
                    _render_sync_card()
                    _render_tracker_defaults_card(core)
                    _render_description_templates_card(core)
                    await _render_devops_contacts_tab(core)

        with ui.tab_panel("tags").classes("p-0 h-full"):
            with ui.scroll_area().classes("w-full h-full"):
                with ui.column().classes("w-full gap-4 p-4"):
                    await _render_devops_tags_tab(core)

        with ui.tab_panel("theme").classes("p-0 h-full"):
            with ui.scroll_area().classes("w-full h-full"):
                with ui.column().classes("w-full gap-4 p-4"):
                    await _render_theme_tab(core)

        with ui.tab_panel("data").classes("p-0 h-full"):
            with ui.scroll_area().classes("w-full h-full"):
                with ui.column().classes("w-full gap-4 p-4"):
                    _render_backup_card(core)
                    _render_time_settings_card(core)
                    await _render_about_card(core)
