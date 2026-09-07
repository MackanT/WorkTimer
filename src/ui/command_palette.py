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
from datetime import datetime
from pathlib import Path

from nicegui import app, ui

_MAX_ROWS = 12
_ROW_SELECTED_STYLE = "background: rgba(56, 189, 248, 0.18);"


def setup_command_palette(core) -> None:
    """Create the per-client palette dialog and its global Ctrl+K binding.
    Called once per client from the SPA shell (root.py)."""
    state = {"commands": [], "filtered": [], "selected": 0}

    with ui.dialog().props("position=top") as dialog:
        with ui.card().classes("p-2 rounded-md").style(
            "width: 560px; max-width: 90vw; margin-top: 8vh;"
        ):
            search = (
                ui.input(placeholder="Search pages, timers, actions…")
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

        for item in (core.ui_config.get("navigation") or {}).values():
            if not item.get("enabled"):
                continue

            async def _go(p=item["path"]):
                _go_to(p)

            cmds.append({
                "label": f"Go to {item['label']}",
                "icon": item.get("icon", "chevron_right"),
                "keywords": "go open page view",
                "action": _go,
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

        if core.devops_engine is not None:

            async def _sync():
                ui.notify("DevOps incremental sync started…", type="info")
                await core.devops_engine.update_devops(incremental=True)
                core.event_bus.emit("devops_refreshed")
                ui.notify("DevOps sync complete", type="positive")

            cmds.append({
                "label": "Sync DevOps (incremental)",
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

        return cmds

    # ── filtering + rendering ──────────────────────────────────────────────
    def _apply_filter():
        q = (search.value or "").strip().lower()
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
                    ui.icon(cmd["icon"], size="xs").classes("shrink-0")
                    ui.label(cmd["label"]).classes("text-sm truncate")
                row.on("click", lambda e, c=cmd: asyncio.create_task(_run(c)))

    async def _run(cmd):
        dialog.close()
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
