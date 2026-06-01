"""
DevOps Board Page — Kanban view from local cache.

v2 — Live mode:
  Drag-and-drop writes to the local DB and calls the Azure DevOps API.
  Card click opens the full update form in a dialog.
  The + button opens the full add form in a dialog.
"""

import asyncio  # kept for _handle_drop which is async
import math
from nicegui import ui
from ..core.app import AppCore
from .. import helpers
from ..ui.elements import toolbar
from ..ui.devops_handlers import DevOpsWorkItemHandlers
from ..ui.devops_forms import render_devops_form


_BOARD_CSS = """<style>
.board-card { cursor: grab; user-select: none; }
.board-card:active { cursor: grabbing; }
.wt-board-col-hover { outline: 2px dashed rgba(100, 160, 255, 0.65) !important; outline-offset: -3px; }
.board-col { transition: outline 0.1s ease; }
</style>"""


async def board_page():
    """DevOps Board — Kanban view of work items from local cache."""
    core = await AppCore.get_or_initialize()
    DO = core.devops_engine

    ui.add_head_html(_BOARD_CSS)

    # Shared board inline styles from centralized style config
    DIALOG_CARD_STYLE = helpers.UI_STYLES.get_inline_style("board", "dialog_card") or (
        "margin: 2rem auto; width: calc(100% - 4rem); max-width: 980px;"
        "max-height: calc(100vh - 4rem); overflow-y: auto;"
    )
    COLUMNS_ROW_STYLE = helpers.UI_STYLES.get_inline_style("board", "columns_row") or (
        "padding: 0.5rem; width: max-content; margin: 0 auto;"
    )
    BOARD_COLUMN_STYLE = (
        "min-width: 272px; max-width: 272px;"
        "background: rgba(255,255,255,0.05);"
        "padding: 0.5rem 0.5rem 0.75rem 0.5rem;"
    )

    # ── board settings from config ───────────────────────────────────────────────────
    _bsettings = core.ui_config.get("board_settings", {})
    TERMINAL_STATES = set(_bsettings.get("terminal_states", ["Closed", "Removed"]))
    _pc_raw = _bsettings.get("priority_colors", {})
    PRIORITY_COLORS = {int(k): v for k, v in _pc_raw.items()} if _pc_raw else {1: "red-5", 2: "orange-4", 3: "blue-4", 4: "grey-4"}
    _pl_raw = _bsettings.get("priority_labels", {})
    PRIORITY_LABELS = {int(k): v for k, v in _pl_raw.items()} if _pl_raw else {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}

    # ── per-client mutable state (captured by all inner closures) ──────────────
    drag_state: dict = {"card": None}
    filter_state: dict = {"customer": None, "type": "User Story"}
    known_cols: dict = {}  # (customer, type) -> ordered list; never shrinks
    ui_state: dict = {"loading": False}

    customer_names: list[str] = []
    if DO is not None and DO.df is not None:
        customer_names = sorted(DO.df["customer_name"].dropna().unique().tolist())
    if customer_names:
        filter_state["customer"] = customer_names[0]

    # Seed known_cols from the ADO column cache (pre-loaded at startup).
    # Without this, the first render derives order from df insertion order which is arbitrary.
    for _cn in customer_names:
        for _wt in ("User Story", "Feature", "Epic"):
            _c = DevOpsWorkItemHandlers.devops_columns_cache.get(_cn, {}).get(_wt)
            if _c:
                known_cols[(_cn, _wt)] = list(_c)

    # ── data helpers ───────────────────────────────────────────────────────────
    def _column_order(customer: str, item_type: str) -> list[str]:
        """Return ordered column list; once a column is known it stays visible."""
        key = (customer, item_type)
        cached = DevOpsWorkItemHandlers.devops_columns_cache.get(customer, {}).get(item_type)
        if cached:
            result = list(cached)
            for c in known_cols.get(key, []):
                if c not in result:
                    result.append(c)
            result = _sort_done_columns_last(_dedupe_columns(result))
            known_cols[key] = result
            return result
        # Fallback: merge previously-seen columns with current df values (never shrinks)
        result = list(known_cols.get(key, []))
        if DO is not None and DO.df is not None:
            mask = DO.df["type"] == item_type
            if customer:
                mask &= DO.df["customer_name"] == customer
            for c in DO.df[mask]["board_column"].dropna().unique().tolist():
                if c and c not in result:
                    result.append(c)
        result = _sort_done_columns_last(_dedupe_columns(result))
        known_cols[key] = result
        return result

    def _col_norm(value: str) -> str:
        return str(value or "").strip().lower()

    def _dedupe_columns(cols: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for c in cols:
            cs = str(c or "").strip()
            if not cs:
                continue
            key = _col_norm(cs)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(cs)
        return deduped

    def _sort_done_columns_last(cols: list[str]) -> list[str]:
        done_tokens = {"done", "closed", "resolved", "completed"}
        normal = [c for c in cols if _col_norm(c) not in done_tokens]
        done = [c for c in cols if _col_norm(c) in done_tokens]
        return normal + done

    def _canonical_column_name(raw_name: str, ordered_cols: list[str]) -> str:
        raw_norm = _col_norm(raw_name)
        if not raw_norm:
            return "— Unassigned —"
        for col in ordered_cols:
            if _col_norm(col) == raw_norm:
                return col
        return str(raw_name).strip()

    def _board_data() -> dict[str, list[dict]]:
        """Return {col_name: [row_dict, ...]} ordered by ADO column order."""
        if DO is None or DO.df is None:
            return {}
        cust = filter_state["customer"]
        wtype = filter_state["type"]
        mask = (DO.df["type"] == wtype) & (~DO.df["state"].isin(TERMINAL_STATES))
        if cust:
            mask &= DO.df["customer_name"] == cust

        ordered_cols = _column_order(cust, wtype)
        data: dict[str, list[dict]] = {c: [] for c in ordered_cols}
        for _, row in DO.df[mask].iterrows():
            raw_col = str(row.get("board_column") or "")
            col = _canonical_column_name(raw_col, ordered_cols)
            data.setdefault(col, []).append(row.to_dict())
        return data

    async def _reload_board_data(show_notify: bool = False, notify_msg: str = ""):
        if DO is None:
            return
        ui_state["loading"] = True
        render_board.refresh()
        await DO.load_df()
        parent_label_cache.clear()
        ui_state["loading"] = False
        render_board.refresh()
        if show_notify and notify_msg:
            ui.notify(notify_msg, type="positive", position="bottom-right")

    # ── move logic (shared by drag-drop and click-to-edit) ────────────────────
    async def _do_move(item_id: int, title: str, customer: str, source_col: str, target_col: str):
        """Persist a column change: local DB write → ADO API call → df reload."""
        if DO is None:
            return

        await DO.query_engine.function_db(
            "update_devops_item_fields",
            work_item_id=item_id,
            fields={"board_column": target_col, "board_column_done": 0},
        )

        if DO.manager:
            try:
                ok, api_msg = await asyncio.to_thread(
                    DO.manager.set_board_column, customer, item_id, target_col
                )
            except Exception as exc:
                ok, api_msg = False, str(exc)

            if ok:
                core.logger.info(
                    f"[BOARD] #{item_id} '{title}' ({customer}): '{source_col}' → '{target_col}'"
                )
            else:
                core.logger.warning(f"[BOARD] ADO sync failed for #{item_id}: {api_msg}")
                ui.notify(
                    f"ADO sync failed: {api_msg}",
                    type="warning",
                    position="bottom-right",
                    timeout=6000,
                )

        # Optimistic in-memory update, then reload from DB
        if DO.df is not None:
            DO.df.loc[DO.df["id"] == item_id, "board_column"] = target_col
            DO.df.loc[DO.df["id"] == item_id, "board_column_done"] = 0
        await _reload_board_data(show_notify=False)

    # ── drag handlers ──────────────────────────────────────────────────────────
    def _handle_dragstart(row: dict):
        drag_state["card"] = row

    def _handle_dragend():
        drag_state["card"] = None

    async def _handle_drop(target_col: str, col_el):
        col_el.classes(remove="wt-board-col-hover")
        card_data = drag_state.get("card")
        if not card_data:
            return
        source_col = str(card_data.get("board_column") or "")
        drag_state["card"] = None

        if source_col == target_col:
            return

        item_id = int(card_data.get("id", 0))
        title = str(card_data.get("title") or "")
        customer = str(card_data.get("customer_name") or "")

        ui.notify(
            f"#{item_id}: {source_col} → {target_col}",
            type="info",
            position="bottom-right",
            timeout=3000,
        )
        await _do_move(item_id, title, customer, source_col, target_col)
        render_board.refresh()

    # ── click-to-edit dialog (full update form) ──────────────────────────────────
    async def _on_card_click(row: dict):
        """Open the full DevOps update form in a dialog."""
        item_id = int(row.get("id", 0))
        item_type = str(row.get("type", "User Story"))
        title = str(row.get("title", ""))
        customer = str(row.get("customer_name", ""))
        priority_val = row.get("priority")
        display_name = f"{item_type}: {item_id} - {title}"

        update_cfg = (
            core.ui_config
            .get("board_devops_forms", {})
            .get("update", {})
        )

        with ui.dialog().props("maximized") as dlg:
            with (
                ui.card()
                .style(DIALOG_CARD_STYLE)
                .props("flat bordered")
            ):
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
                        ui.label("Your edits in this work item will be lost.").classes("text-xs text-grey-5")
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

                # ── Item header: shows which item we’re editing ────────────────
                p_color = PRIORITY_COLORS.get(priority_val, "grey-4")
                p_label = PRIORITY_LABELS.get(priority_val, "")
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
                    ui.button("Update", icon="save", on_click=_submit_from_header).props("dense color=primary")
                    ui.button("Cancel", icon="close", on_click=_confirm_discard_or_close).props("flat dense color=grey-6")
                ui.separator()

                # Show lightweight skeleton while form/options/description are hydrating.
                loading_box = ui.column().classes("w-full gap-2").style("padding: 0.75rem;")
                with loading_box:
                    ui.skeleton("text", width="35%")
                    ui.skeleton("rect", width="100%", height="52px")
                    ui.skeleton("rect", width="100%", height="52px")
                    ui.skeleton("rect", width="100%", height="52px")
                    ui.skeleton("rect", width="100%", height="220px")

                # Open first so the user sees immediate feedback, then hydrate the form.
                dlg.open()
                await asyncio.sleep(0)

                async def _on_update_success():
                    dlg.close()
                    await _reload_board_data(show_notify=False)

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

                    # Start tracking user edits after programmatic prefill is complete.
                    dirty_state["programmatic"] = False
                    watch_fields = ["state", "assigned_to", "priority", "description_editor"]
                    for field_name in watch_fields:
                        w = widgets.get(field_name)
                        if w:
                            w.on_value_change(_mark_dirty)

                loading_box.clear()

    # ── add-item dialog (full add form) ───────────────────────────────────────
    async def _open_add_dialog():
        """Open the full DevOps add form in a dialog."""
        add_cfg = (
            core.ui_config
            .get("board_devops_forms", {})
            .get("add", {})
        )

        with ui.dialog().props("maximized") as dlg:
            with (
                ui.card()
                .style(DIALOG_CARD_STYLE)
                .props("flat bordered")
            ):
                form_actions: dict = {"submit": None}

                async def _submit_from_header():
                    submit_fn = form_actions.get("submit")
                    if submit_fn:
                        await submit_fn()

                # Match the update dialog look with a top context bar.
                with ui.row().classes("items-center gap-2 no-wrap w-full").style(
                    "padding: 0.6rem 0.8rem; flex-shrink: 0;"
                ):
                    ui.icon("add_circle", size="16px").classes("text-primary shrink-0")
                    ui.label("New Work Item").classes("text-grey-5 text-xs uppercase tracking-wide shrink-0")
                    ui.label("·").classes("text-grey-5 text-xs shrink-0")
                    type_label = ui.label(filter_state.get("type", "User Story")).classes("text-grey-5 text-xs shrink-0")
                    customer_label = ui.label(filter_state.get("customer", "")).classes("text-sm font-semibold flex-1").style(
                        "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                    )
                    ui.space()
                    ui.button("Add", icon="save", on_click=_submit_from_header).props("dense color=primary")
                    ui.button("Cancel", icon="close", on_click=dlg.close).props("flat dense color=grey-6")
                ui.separator()

                async def _on_add_success():
                    dlg.close()
                    await _reload_board_data(show_notify=False)

                result = await render_devops_form(
                    core, "add", add_cfg,
                    on_success=_on_add_success,
                    show_internal_header=False,
                )

                _, widgets, _, submit_fn = result if result else (None, {}, None, None)
                form_actions["submit"] = submit_fn

                if widgets:
                    cust = filter_state.get("customer")
                    if cust and "customer_name" in widgets:
                        widgets["customer_name"].widget.value = cust
                        widgets["customer_name"].widget.update()
                    wtype = filter_state.get("type", "User Story")
                    if wtype and "work_item_type" in widgets:
                        widgets["work_item_type"].widget.value = wtype
                        widgets["work_item_type"].widget.update()

                    def _sync_add_header(_e=None):
                        if "work_item_type" in widgets:
                            type_label.set_text(str(widgets["work_item_type"].widget.value or "User Story"))
                        if "customer_name" in widgets:
                            customer_label.set_text(str(widgets["customer_name"].widget.value or ""))

                    if "work_item_type" in widgets:
                        widgets["work_item_type"].on_value_change(_sync_add_header)
                    if "customer_name" in widgets:
                        widgets["customer_name"].on_value_change(_sync_add_header)
                    _sync_add_header()

        dlg.open()

    # ── card renderer ──────────────────────────────────────────────────────────
    def _render_card(row: dict):
        item_id = int(row.get("id", 0))
        title = str(row.get("title") or "Untitled")
        priority = row.get("priority")
        assigned = str(row.get("assigned_to") or "")
        board_column_done = bool(row.get("board_column_done", 0))
        parent_id = row.get("parent_id")
        p_color = PRIORITY_COLORS.get(priority, "grey-4")
        p_label = PRIORITY_LABELS.get(priority, "")

        # Resolve parent display name from the df (cached to avoid repeated scans)
        parent_label: str = ""
        try:
            # parent_id can arrive as pandas NaN (float), which cannot be converted to int.
            if parent_id is not None and not (
                isinstance(parent_id, float) and math.isnan(parent_id)
            ):
                parent_label = _parent_label(int(parent_id))
        except (TypeError, ValueError):
            parent_label = ""

        with (
            ui.card()
            .classes("board-card w-full rounded shadow-sm")
            .style("padding: 0.4rem 0.6rem;")
            .props("flat bordered draggable=true")
        ) as card:
            card.on("dragstart", lambda e, r=row: _handle_dragstart(r))
            card.on("dragend", lambda e: _handle_dragend())

            def _make_card_click(r):
                async def handler(e):
                    await _on_card_click(r)
                return handler
            card.on("click", _make_card_click(row))

            with ui.row().classes("items-center gap-1 w-full no-wrap"):
                if priority:
                    ui.icon("circle", size="12px").classes(f"text-{p_color} shrink-0").tooltip(
                        f"Priority: {p_label}"
                    )
                ui.label(f"#{item_id}").classes("text-xs text-grey-5 shrink-0")
                ui.space()
                # Show a "Done" chip only when the item is in the done sub-state
                if board_column_done:
                    ui.badge("✓ Done").props("color=green-7 rounded").classes("text-xs shrink-0")

            ui.label(title).classes("text-sm").style(
                "word-break:break-word; white-space:normal; line-height:1.3; margin-top:2px;"
            )
            if parent_label:
                with ui.row().classes("items-center gap-1").style("margin-top:3px;"):
                    ui.icon("account_tree", size="12px").classes("text-grey-5 shrink-0")
                    ui.label(parent_label).classes("text-xs text-grey-5").style(
                        "overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:200px;"
                    )
            if assigned:
                ui.label(f"👤 {assigned}").classes("text-xs text-grey-5").style("margin-top:3px;")

    parent_label_cache: dict[int, str] = {}

    def _parent_label(parent_id: int) -> str:
        if parent_id in parent_label_cache:
            return parent_label_cache[parent_id]
        if DO is None or DO.df is None:
            return ""
        try:
            p_match = DO.df[DO.df["id"] == int(parent_id)]
            if p_match.empty:
                parent_label_cache[parent_id] = ""
                return ""
            pr = p_match.iloc[0]
            label = f"{pr['type']}: {int(pr['id'])} – {str(pr['title'] or '')[:30]}"
            parent_label_cache[parent_id] = label
            return label
        except Exception:
            parent_label_cache[parent_id] = ""
            return ""

    # ── refreshable board ──────────────────────────────────────────────────────
    @ui.refreshable
    def render_board():
        cust = filter_state["customer"]

        if ui_state["loading"]:
            with ui.row().classes("gap-3 items-start flex-nowrap").style(COLUMNS_ROW_STYLE):
                for _ in range(4):
                    with ui.column().classes("board-col rounded-lg gap-2").style(BOARD_COLUMN_STYLE):
                        ui.skeleton("text", width="70%").classes("mb-2")
                        ui.separator().classes("opacity-20")
                        for _ in range(3):
                            ui.skeleton("rect", width="100%", height="72px")
            return

        if not cust:
            with ui.column().classes("items-center justify-center w-full").style("padding: 4rem;"):
                ui.icon("view_kanban", size="xl").classes("text-grey-6")
                ui.label("No customers with DevOps data available.").classes("text-grey-5 mt-2")
            return

        data = _board_data()
        if not data:
            with ui.column().classes("items-center justify-center w-full").style("padding: 4rem;"):
                ui.icon("inbox", size="xl").classes("text-grey-6")
                ui.label(
                    f"No active {filter_state['type']} items for {cust}."
                ).classes("text-grey-5 mt-2")
            return

        with ui.row().classes("gap-3 items-start flex-nowrap").style(COLUMNS_ROW_STYLE):
            for col_name, cards in data.items():
                with (
                    ui.column()
                    .classes("board-col rounded-lg gap-2")
                    .style(BOARD_COLUMN_STYLE)
                ) as col_el:
                    # Column header
                    with ui.row().classes("items-center gap-2 w-full").style("padding: 0.1rem 0.2rem 0.3rem;"):
                        ui.label(col_name).classes("text-sm font-semibold flex-1").style(
                            "color: rgba(255,255,255,0.8);"
                        )
                        ui.badge(str(len(cards))).props("color=grey-7 rounded")

                    ui.separator().classes("opacity-20")

                    # Drop zone on the column container
                    col_el.on("dragover.prevent", lambda e: None)
                    col_el.on("dragenter", lambda e, c=col_el: c.classes(add="wt-board-col-hover"))
                    col_el.on("dragleave", lambda e, c=col_el: c.classes(remove="wt-board-col-hover"))

                    def _make_drop_handler(cn, c):
                        async def handler(e):
                            await _handle_drop(cn, c)
                        return handler

                    col_el.on("drop", _make_drop_handler(col_name, col_el))

                    # Cards
                    with ui.column().classes("gap-2 w-full"):
                        for card_row in cards:
                            _render_card(card_row)

    # ── toolbar ────────────────────────────────────────────────────────────────
    with toolbar(core.theme):
        with ui.row().classes("items-center gap-3 w-full flex-nowrap"):
            ui.label("Board").classes("text-white font-bold shrink-0")

            # Customer tabs (if multiple)
            if len(customer_names) > 1:
                with (
                    ui.tabs(value=filter_state["customer"])
                    .props(
                        f"horizontal dense "
                        f'active-color="{core.theme.get("accent")}" '
                        f'indicator-color="{core.theme.get("accent")}"'
                    )
                    .classes(helpers.UI_STYLES.get_layout_classes("tab_label"))
                ) as cust_tabs:
                    for c in customer_names:
                        ui.tab(c, label=c)

                async def _on_customer_change(e):
                    filter_state["customer"] = e.value
                    render_board.refresh()

                cust_tabs.on_value_change(_on_customer_change)
            elif customer_names:
                ui.label(customer_names[0]).classes("text-white text-sm shrink-0")

            ui.space()

            # Item type toggle
            type_toggle = (
                ui.toggle(
                    ["User Story", "Feature", "Epic"],
                    value=filter_state["type"],
                )
                .props("dense")
                .classes("shrink-0")
            )

            async def _on_type_change(e):
                filter_state["type"] = e.value
                render_board.refresh()

            type_toggle.on_value_change(_on_type_change)

            # Refresh from local cache (no API)
            async def _on_refresh():
                await _reload_board_data(
                    show_notify=True,
                    notify_msg="Board refreshed from local cache",
                )

            ui.button(icon="refresh", on_click=_on_refresh).props(
                "flat dense color=white"
            ).tooltip("Reload from local DB (no API call)")

            ui.button(icon="add", on_click=_open_add_dialog).props(
                "flat dense color=white"
            ).tooltip("Add new DevOps work item")

    # ── board area (scrollable) ────────────────────────────────────────────────
    with (
        ui.element("div")
        .classes("wt-page-content overflow-x-auto overflow-y-auto")
        .style("padding: 0.25rem 0.5rem;")
    ):
        # This wrapper centers the entire scroll content area when columns are sparse,
        # while still allowing natural left-to-right horizontal scrolling when wide.
        with ui.element("div").style("width: max-content; min-width: 100%; margin: 0 auto;"):
            render_board()
