"""Global command palette — Ctrl+K from anywhere.

Fuzzy-searchable commands: jump to any page, start a timer on any project,
stop a running timer (routed through the normal stop dialog on the Time page,
so comment / project / stop-time still happen), plus one-shot actions
(DevOps sync, database backup).

Ctrl+K composition: the SQL query editor's comment chord attaches in capture
phase on its own DOM and stops propagation, so inside that editor Ctrl+K stays
the comment chord; everywhere else the keypress reaches the document-level
listener here. The browser's own Ctrl+K (address-bar search) is suppressed with
a capture-phase preventDefault that skips the editor. NiceGUI's keyboard
element ignores keys typed in input/textarea fields, so Ctrl+K inside a text
field neither opens the palette nor loses your keystroke.
"""

import asyncio
import math
from datetime import datetime
from pathlib import Path

from nicegui import app, ui

from .work_item_forms import open_add_work_item_dialog, open_work_item_dialog

_MAX_ROWS = 12
_ROW_SELECTED_STYLE = "background: rgba(56, 189, 248, 0.18);"

# Find-mode "done" styling mirrors the hierarchy's grey-out rule.
_DONE_STATES = {"Resolved", "Closed", "Removed"}
_DONE_COLUMN_TOKENS = {"done", "closed", "resolved", "completed"}


def setup_command_palette(core) -> None:
    """Create the per-client palette dialog and its global Ctrl+K binding.
    Called once per client from the SPA shell (root.py)."""
    state = {"commands": [], "filtered": [], "selected": 0}

    # Neutral shell-level host for UI that command actions create (e.g. the
    # work-item dialog from find-mode). Actions run in the palette's slot
    # context — but the palette dialog is closed right before they run, and a
    # dialog nested in a closed dialog's card never renders (it would only
    # appear once the palette re-opens and remounts it).
    action_host = ui.element("div").classes("hidden")

    with ui.dialog().props("position=top") as dialog:
        with ui.card().classes("p-2 rounded-md").style(
            "width: 560px; max-width: 90vw; margin-top: 8vh;"
        ):
            search = (
                ui.input(placeholder="Search pages, timers, actions…  (# finds work items)")
                .props("dense outlined autofocus")
                .classes("w-full")
            )
            results = ui.column().classes("w-full gap-0 mt-1")

    # ── shared helpers ─────────────────────────────────────────────────────
    async def _emit_active_timers():
        """Refresh the nav bar's running-timer pills (mirrors the Time page's
        indicator query, so palette timer actions update it from any page)."""
        result = await core.query_engine.query_db(
            "select c.customer_name, p.project_name from time t "
            "join customers c on t.customer_id = c.customer_id "
            "join projects p on t.project_id = p.project_id "
            "where t.end_time is null order by c.customer_name, p.project_name"
        )
        names = (
            [f"{r['customer_name']} / {r['project_name']}" for _, r in result.iterrows()]
            if not result.empty else []
        )
        core.event_bus.emit(
            "active_timer_count_changed", count=len(names), names=names
        )

    def _go_to(path: str):
        core.nav_bar.set_active(path, core.theme)
        if getattr(core.nav_bar, "on_navigate", None):
            asyncio.create_task(core.nav_bar.on_navigate())
        ui.navigate.to(path)

    # ── command registry (rebuilt on every open, so timers/projects are fresh) ──
    async def _build_commands() -> list:
        cmds = []

        # Dropdown-menu nav entries (e.g. Data Input) have no page behind
        # their path — navigating there 404s. Their dialogs get their own
        # palette commands below, so skip the "Go to" for them.
        menu_paths = set(getattr(core.nav_bar, "menu_providers", {}) or {})

        for item in (core.ui_config.get("navigation") or {}).values():
            if not item.get("enabled") or item.get("path") in menu_paths:
                continue

            async def _go(p=item["path"]):
                _go_to(p)

            cmds.append({
                "label": f"Go to {item['label']}",
                "icon": item.get("icon", "chevron_right"),
                "keywords": "go open page view",
                "action": _go,
            })

        # Board views — Hierarchy has no nav entry (it's the board's view
        # toggle), so jumping straight to it sets the remembered view first.
        for view_key, view_label, view_icon, view_kw in (
            ("board", "Go to Board — Kanban view", "view_kanban", "kanban columns cards"),
            ("hierarchy", "Go to Board — Hierarchy view", "account_tree", "hierarchy tree epic graph"),
        ):
            async def _go_board_view(v=view_key):
                app.storage.user["devops_view"] = v
                _go_to("/board")

            cmds.append({
                "label": view_label,
                "icon": view_icon,
                "keywords": f"go open page {view_kw}",
                "action": _go_board_view,
            })

        # Create work items — the shared add dialog opens right over whatever
        # page is showing (no navigation). Seeded with the board's remembered
        # customer; a successful add emits devops_refreshed so an open board
        # reloads.
        # Prefer the READY global engine: core.tracker_engine only re-adopts
        # it on the next page render, so after a tracker/customer change the
        # per-client reference lags until a navigation (the palette would
        # miss a newly linked tracker's levels).
        from ..core.app import get_global_tracker_engine

        engine = get_global_tracker_engine() or core.tracker_engine
        if engine is not None:
            DO = engine
            # Union of levels across ALL connected trackers (Azure: Epic /
            # Feature / User Story; Jira adds Story / Sub-task). Each command
            # presets a customer whose tracker HAS that level — preferring the
            # board's remembered customer — so the type survives the dialog's
            # per-tracker validity snap.
            remembered = app.storage.user.get("devops_customer")
            type_presets: dict = {}
            for cust in (DO.manager.clients if DO.manager else {}):
                for wtype in DO.type_hierarchy(cust):
                    if cust == remembered or wtype not in type_presets:
                        type_presets[wtype] = cust
            if not type_presets:
                type_presets = {t: remembered for t in DO.type_hierarchy()}

            for wtype, preset_cust in type_presets.items():

                async def _add_item(t=wtype, c=preset_cust):
                    async def _added():
                        core.event_bus.emit("devops_refreshed")

                    dlg = await open_add_work_item_dialog(
                        core,
                        preset_customer=c,
                        preset_type=t,
                        on_success=_added,
                    )
                    if dlg is not None:
                        # Lives in the long-lived shell host — dispose on close.
                        dlg.on("hide", lambda: dlg.delete())

                cmds.append({
                    "label": f"Add {wtype}",
                    "icon": "add_circle",
                    "keywords": "create new devops jira work item ticket issue",
                    "action": _add_item,
                })

        QE = core.query_engine
        running = await QE.query_db(
            "select t.customer_id, t.project_id, c.customer_name, p.project_name "
            "from time t "
            "join customers c on t.customer_id = c.customer_id "
            "join projects p on t.project_id = p.project_id "
            "where t.end_time is null order by c.customer_name, p.project_name"
        )
        running_pairs = set()
        for _, r in running.iterrows():
            cid, pid = int(r["customer_id"]), int(r["project_id"])
            running_pairs.add((cid, pid))
            lbl = f"{r['customer_name']} / {r['project_name']}"

            async def _stop(c=cid, p=pid):
                # The stop flow needs the Time page's dialog (comment / project /
                # stop-time), so hand over via a pending request: the event covers
                # "already on /time", the storage flag covers the fresh page load.
                app.storage.client["palette_stop"] = [c, p]
                core.event_bus.emit("palette_stop_timer")
                _go_to("/time")

            cmds.append({
                "label": f"Stop timer — {lbl}",
                "icon": "stop_circle",
                "keywords": "stop end finish running timer",
                "action": _stop,
            })

        projects = await QE.query_db(
            "select c.customer_id, c.customer_name, p.project_id, p.project_name "
            "from customers c join projects p on p.customer_id = c.customer_id "
            "where c.is_current = 1 and p.is_current = 1 "
            "order by c.customer_name, p.project_name"
        )
        for _, r in projects.iterrows():
            cid, pid = int(r["customer_id"]), int(r["project_id"])
            if (cid, pid) in running_pairs:
                continue
            lbl = f"{r['customer_name']} / {r['project_name']}"

            async def _start(c=cid, p=pid, name=lbl):
                await QE.function_db("insert_time_row", c, p)
                await _emit_active_timers()
                core.event_bus.emit("timer_state_changed")
                ui.notify(f"Timer started — {name}", type="positive")

            cmds.append({
                "label": f"Start timer — {lbl}",
                "icon": "play_circle",
                "keywords": "start begin track timer",
                "action": _start,
            })

        if core.tracker_engine is not None:

            async def _sync():
                ui.notify("Tracker incremental sync started…", type="info")
                await core.tracker_engine.refresh_tracker_data(incremental=True)
                core.event_bus.emit("devops_refreshed")
                ui.notify("Tracker sync complete", type="positive")

            cmds.append({
                "label": "Sync trackers (incremental)",
                "icon": "sync",
                "keywords": "devops azure refresh update board",
                "action": _sync,
            })

        async def _backup():
            # Mirrors Settings → Backup now (same folder, naming and keep-10).
            try:
                backups_dir = Path(core.query_engine.file_name).parent / "backups"
                backups_dir.mkdir(parents=True, exist_ok=True)
                dest = backups_dir / f"worktimer_{datetime.now():%Y-%m-%d_%H%M%S}.db"
                await asyncio.to_thread(core.query_engine.db.backup_to, str(dest))
                for old in sorted(backups_dir.glob("worktimer_*.db"), reverse=True)[10:]:
                    old.unlink()
                ui.notify(f"Backup saved: backups/{dest.name}", type="positive")
            except Exception as ex:
                core.logger.error(f"Backup failed: {ex}")
                ui.notify(f"Backup failed: {ex}", type="negative")

        cmds.append({
            "label": "Backup database now",
            "icon": "save",
            "keywords": "database backup export save copy",
            "action": _backup,
        })

        # Data-management shortcuts — one command per entity operation from
        # the config (customer/tracker/project/…): opens the entity dialog
        # right over the current page, on the right operation tab with its
        # first field focused (same no-navigation pattern as the work-item
        # add commands).
        from ..pages.add_data import entity_sections, open_entity_dialog

        _OP_LABELS = {"reenable": "Re-enable"}
        for entity, section in entity_sections(core).items():
            meta = section.get("meta", {})
            for op in meta.get("options", []):
                verb = _OP_LABELS.get(op, op.capitalize())

                async def _open_input(e=entity, o=op):
                    await open_entity_dialog(core, e, operation=o)

                cmds.append({
                    "label": f"{verb} {entity}",
                    "icon": meta.get("icon", "input"),
                    "keywords": (
                        f"data input form manage new edit "
                        f"{meta.get('friendly_name', '')}"
                    ).lower(),
                    "action": _open_input,
                })

        return cmds

    # ── find-mode ("#…"): search work items instead of commands ────────────
    # Same matching as the board's search box — case-insensitive substring,
    # all words must match, across title / assignee / state / column / #id and
    # the ancestor chain — but spanning ALL customers, types and states
    # (closed included; looking up a finished ticket is half the point).
    def _item_haystack():
        """Lowercased search text per work-item row; built once per palette open."""
        if state.get("_item_index") is not None:
            return state["_item_index"]
        df = core.tracker_engine.df if core.tracker_engine is not None else None
        if df is None or df.empty:
            state["_item_index"] = (None, None)
            return state["_item_index"]
        cols = [
            c for c in ("title", "assigned_to", "state", "board_column",
                        "customer_name", "type", "description")
            if c in df.columns
        ]
        hay = df[cols].fillna("").astype(str).agg(" ".join, axis=1)
        hay = hay + " #" + df["id"].astype(str)
        if "parent_id" in df.columns:
            id_to_title = {
                int(i): str(t) for i, t in zip(df["id"], df["title"].fillna(""))
            }
            id_to_parent = {int(i): p for i, p in zip(df["id"], df["parent_id"])}

            def _ancestors(pid):
                parts, seen = [], set()
                while pid is not None and not (
                    isinstance(pid, float) and math.isnan(pid)
                ):
                    try:
                        ip = int(pid)
                    except (TypeError, ValueError):
                        break
                    if ip in seen:
                        break
                    seen.add(ip)
                    parts.append(f"#{ip} {id_to_title.get(ip, '')}")
                    pid = id_to_parent.get(ip)
                return " ".join(parts)

            hay = hay + " " + df["parent_id"].map(_ancestors)
        state["_item_index"] = (df, hay.str.lower())
        return state["_item_index"]

    def _find_work_items(q: str) -> list:
        df, hay = _item_haystack()
        if df is None:
            return []
        sub = df
        for part in q.split():
            sub = sub[hay.loc[sub.index].str.contains(part, regex=False, na=False)]
            if sub.empty:
                return []
        if "changed_date" in sub.columns:
            sub = sub.sort_values("changed_date", ascending=False)
        entries = []
        for _, r in sub.head(_MAX_ROWS).iterrows():
            row_dict = r.to_dict()
            done = (
                str(r.get("state") or "") in _DONE_STATES
                or str(r.get("board_column") or "").strip().lower()
                in _DONE_COLUMN_TOKENS
            )

            async def _open_item(item=row_dict):
                # The dialog lives in the long-lived shell host — delete it once
                # closed so repeated lookups don't accumulate dead elements.
                dlg = await open_work_item_dialog(core, item)
                if dlg is not None:
                    dlg.on("hide", lambda: dlg.delete())

            entries.append({
                "label": f"{r.get('display_name') or ''}  ·  {r.get('customer_name')}",
                "_color": state.get("cust_colors", {}).get(r.get("customer_name")),
                "_done": done,
                "action": _open_item,
            })
        return entries

    # ── filtering + rendering ──────────────────────────────────────────────
    def _apply_filter():
        raw = (search.value or "").strip()
        if raw.startswith("#"):
            state["filtered"] = _find_work_items(raw[1:].strip().lower())
            state["selected"] = 0
            _render_results()
            return
        q = raw.lower()
        if q:
            state["filtered"] = [
                c for c in state["commands"]
                if all(
                    part in (c["label"] + " " + c.get("keywords", "")).lower()
                    for part in q.split()
                )
            ][:_MAX_ROWS]
        else:
            state["filtered"] = state["commands"][:_MAX_ROWS]
        state["selected"] = 0
        _render_results()

    def _render_results():
        results.clear()
        with results:
            if not state["filtered"]:
                ui.label("No matches").classes("text-sm text-grey-6 px-2 py-1")
                return
            for i, cmd in enumerate(state["filtered"]):
                row = ui.row().classes(
                    "w-full items-center gap-2 px-2 py-1 rounded cursor-pointer no-wrap"
                )
                if i == state["selected"]:
                    row.style(_ROW_SELECTED_STYLE)
                with row:
                    if "_color" in cmd:
                        # Work-item row: customer colour dot, done items greyed.
                        ui.element("div").style(
                            "width:10px; height:10px; border-radius:50%; "
                            f"flex:0 0 auto; background:{cmd['_color'] or '#64748b'};"
                        )
                        lbl_cls = "text-sm truncate"
                        if cmd.get("_done"):
                            lbl_cls += " text-grey-6"
                        ui.label(cmd["label"]).classes(lbl_cls)
                    else:
                        ui.icon(cmd["icon"], size="xs").classes("shrink-0")
                        ui.label(cmd["label"]).classes("text-sm truncate")
                row.on("click", lambda e, c=cmd: asyncio.create_task(_run(c)))

    async def _run(cmd):
        dialog.close()
        # Enter the host's slot explicitly: actions may create dialogs, and this
        # also gives the click path (a bare asyncio task) a valid slot context.
        with action_host:
            await cmd["action"]()

    def _move(delta: int):
        if state["filtered"]:
            state["selected"] = (state["selected"] + delta) % len(state["filtered"])
            _render_results()

    async def _run_selected():
        if state["filtered"]:
            await _run(state["filtered"][state["selected"]])

    search.on_value_change(_apply_filter)
    search.on("keydown.down.prevent", lambda: _move(1))
    search.on("keydown.up.prevent", lambda: _move(-1))
    search.on("keydown.enter.prevent", _run_selected)

    # ── opening ────────────────────────────────────────────────────────────
    async def _open_palette():
        state["commands"] = await _build_commands()
        state["_item_index"] = None  # find-mode index rebuilt per open (fresh df)
        colors_df = await core.query_engine.query_db(
            "select customer_name, color from customers where is_current = 1"
        )
        state["cust_colors"] = {
            r["customer_name"]: r["color"]
            for _, r in colors_df.iterrows()
            if r["color"]
        }
        search.set_value("")
        _apply_filter()
        dialog.open()
        search.run_method("focus")

    async def _handle_key(e):
        if (
            e.action.keydown and not e.action.repeat
            and e.modifiers.ctrl and e.key == "k"
        ):
            await _open_palette()

    ui.keyboard(on_key=_handle_key)

    # Suppress the browser's own Ctrl+K (address-bar search) everywhere except
    # inside the SQL editor, whose comment chord owns the key there.
    ui.run_javascript(
        """
        if (!window._wtPaletteKey) {
            window._wtPaletteKey = true;
            document.addEventListener('keydown', function (e) {
                if (e.ctrlKey && (e.key === 'k' || e.key === 'K')
                    && !(e.target && e.target.closest && e.target.closest('.cm-editor'))) {
                    e.preventDefault();
                }
            }, true);
        }
        """
    )
