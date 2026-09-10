"""
DevOps Board Page — Kanban view from local cache.

v2 — Live mode:
  Drag-and-drop writes to the local DB and calls the Azure DevOps API.
  Card click opens the full update form in a dialog.
  The + button opens the full add form in a dialog.
"""

import asyncio
import math
from nicegui import app, context, ui
from ..core.app import AppCore
from .. import helpers
from ..ui.elements import page_card, segmented_chips, toolbar, toolbar_group
from ..ui.devops_handlers import DevOpsWorkItemHandlers
from ..ui.devops_forms import open_add_work_item_dialog, open_work_item_dialog
from ..trackers.base import DEFAULT_TYPE_HIERARCHY
from .hierarchy import create_hierarchy_view


_BOARD_CSS = """<style>
/* Cards: rounded, borderless, soft shadow — matches the app's cards and the
   hierarchy nodes. Shadow lifts a little on hover for affordance. */
.board-card { cursor: grab; user-select: none; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35); transition: box-shadow 0.15s ease, transform 0.15s ease; }
.board-card:hover { box-shadow: 0 4px 14px rgba(0, 0, 0, 0.45); transform: translateY(-1px); }
.board-card:active { cursor: grabbing; }
.wt-board-col-hover { outline: 2px dashed rgba(100, 160, 255, 0.65) !important; outline-offset: -3px; }
.board-col { transition: outline 0.1s ease; }
</style>"""


async def board_page():
    """DevOps Board — Kanban view of work items from local cache."""
    core = await AppCore.get_or_initialize()
    DO = core.devops_engine
    muted = core.theme.get("muted")  # theme muted-text token

    # Inject once per client — SPA re-visits would stack duplicate <style> blocks.
    if not app.storage.client.get("board_css_injected"):
        app.storage.client["board_css_injected"] = True
        ui.add_head_html(_BOARD_CSS)

    # Shared board inline styles from centralized style config
    DIALOG_CARD_STYLE = helpers.UI_STYLES.get_inline_style("board", "dialog_card") or (
        "margin: 2rem auto; width: calc(100% - 4rem); max-width: 980px;"
        "max-height: calc(100vh - 4rem); overflow-y: auto;"
    )
    COLUMNS_ROW_STYLE = helpers.UI_STYLES.get_inline_style("board", "columns_row") or (
        "padding: 0.5rem; width: 100%;"
    )
    # Sizing only — each column/zone is its own ui.card() (like time_tracking's
    # entity_card_shell), so it gets the app's normal card surface/background for free.
    BOARD_COLUMN_STYLE = (
        "flex: 1 1 272px; min-width: 272px; max-width: 420px;"
        "padding: 0.5rem 0.5rem 0.75rem 0.5rem;"
    )
    DONE_ZONE_STYLE = "flex: 0 0 130px; min-width: 130px; padding: 0.5rem;"

    # ── board settings from config ───────────────────────────────────────────────────
    _bsettings = core.ui_config.get("board_settings", {})
    TERMINAL_STATES = set(_bsettings.get("terminal_states", ["Closed", "Removed"]))
    _pc_raw = _bsettings.get("priority_colors", {})
    PRIORITY_COLORS = {int(k): v for k, v in _pc_raw.items()} if _pc_raw else {1: "red-5", 2: "orange-4", 3: "blue-4", 4: "grey-4"}
    _pl_raw = _bsettings.get("priority_labels", {})
    PRIORITY_LABELS = {int(k): v for k, v in _pl_raw.items()} if _pl_raw else {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}
    DONE_COLUMN_LIMIT = int(_bsettings.get("done_column_limit", 10))
    DONE_TOKENS = {"done", "closed", "resolved", "completed"}

    def _work_item_types(cust: str | None = None) -> tuple:
        """This board's work-item types, leaf-first (chips/tab order) — from the
        customer's tracker provider rather than hard-coded levels."""
        levels = (
            DO.type_hierarchy(cust) if DO is not None else DEFAULT_TYPE_HIERARCHY
        )
        return tuple(reversed(levels))

    # ── per-client mutable state (captured by all inner closures) ──────────────
    drag_state: dict = {"card": None}
    filter_state: dict = {
        "customer": None,
        "type": _work_item_types()[0],
        "search": "",
        "include_done": bool(app.storage.user.get("board_include_done", False)),
    }
    known_cols: dict = {}  # (customer, type) -> ordered list; never shrinks
    ui_state: dict = {"loading": False}

    customer_names: list[str] = []
    if DO is not None and DO.df is not None:
        customer_names = sorted(DO.df["customer_name"].dropna().unique().tolist())
    if customer_names:
        _saved_cust = app.storage.user.get("devops_customer")
        filter_state["customer"] = (
            _saved_cust if _saved_cust in customer_names else customer_names[0]
        )
        # Preferred level for THIS customer's tracker (Jira's leaf is Sub-task
        # but its working level is Story; Azure's leaf User Story is both).
        if DO is not None:
            filter_state["type"] = DO.preferred_type(filter_state["customer"])

    # Per-customer indicator colours (shown as a dot on the customer tabs).
    cust_colors: dict = {}
    if customer_names:
        _cdf = await core.query_engine.query_db(
            "SELECT customer_name, color FROM customers WHERE is_current = 1"
        )
        if not _cdf.empty:
            cust_colors = {
                r["customer_name"]: r["color"]
                for _, r in _cdf.iterrows()
                if r["color"]
            }

    # Board and Hierarchy are two lenses on the same work-item data, toggled in
    # the toolbar. The hierarchy is embedded here (its own page was retired); it
    # reads the shared customer selection.
    view_state = {"view": app.storage.user.get("devops_view", "board")}
    hier = create_hierarchy_view(core, lambda: filter_state["customer"])

    # Seed known_cols from the ADO column cache (pre-loaded at startup).
    # Without this, the first render derives order from df insertion order which is arbitrary.
    for _cn in customer_names:
        for _wt in _work_item_types(_cn):
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
        normal = [c for c in cols if _col_norm(c) not in DONE_TOKENS]
        done = [c for c in cols if _col_norm(c) in DONE_TOKENS]
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
        """Return {col_name: [row_dict, ...]} ordered by ADO column order.

        Done-token columns (Done/Closed/Resolved/Completed) are excluded entirely —
        they have no space-consuming column of their own. Instead they're surfaced
        through the persistent Done drop-zone (see render_done_zone / _done_items).
        """
        if DO is None or DO.df is None:
            return {}
        cust = filter_state["customer"]
        wtype = filter_state["type"]

        base_mask = DO.df["type"] == wtype
        if cust:
            base_mask &= DO.df["customer_name"] == cust

        # Free-text search across each card's visible fields (title, assignee,
        # state, board column, and #id) — case-insensitive substring match.
        # Descriptions are cached as plain text during sync, so they match too.
        query = (filter_state.get("search") or "").strip().lower()
        if query:
            cols = [
                c for c in ("title", "assigned_to", "state", "board_column",
                            "description")
                if c in DO.df.columns
            ]
            haystack = DO.df[cols].fillna("").astype(str).agg(" ".join, axis=1)
            if "id" in DO.df.columns:
                haystack = haystack + " #" + DO.df["id"].astype(str)
            # Fold in each card's ancestor chain (parent → … → epic) as id + title,
            # so searching a parent's key/name surfaces its children.
            if {"id", "parent_id"}.issubset(DO.df.columns):
                id_to_title = {
                    int(i): str(t)
                    for i, t in zip(DO.df["id"], DO.df["title"].fillna(""))
                }
                id_to_parent = {
                    int(i): p for i, p in zip(DO.df["id"], DO.df["parent_id"])
                }

                def _ancestor_text(pid):
                    parts, seen = [], set()
                    while pid is not None and not (
                        isinstance(pid, float) and math.isnan(pid)
                    ):
                        try:
                            ip = int(pid)
                        except (TypeError, ValueError):
                            break
                        if ip in seen:  # guard against any cycle
                            break
                        seen.add(ip)
                        parts.append(f"#{ip} {id_to_title.get(ip, '')}")
                        pid = id_to_parent.get(ip)
                    return " ".join(parts)

                haystack = haystack + " " + DO.df["parent_id"].map(_ancestor_text)
            base_mask &= haystack.str.lower().str.contains(query, regex=False, na=False)

        ordered_cols_all = _column_order(cust, wtype)
        done_cols = {c for c in ordered_cols_all if _col_norm(c) in DONE_TOKENS}

        # "Include done" surfaces Done/closed items too, but only alongside an
        # active search — so it never floods the board with every closed item.
        show_done = bool(filter_state.get("include_done")) and bool(query)
        if show_done:
            ordered_cols = list(ordered_cols_all)   # keep the Done column(s) visible
            row_mask = base_mask                     # include terminal-state items
            skip_cols: set = set()
        else:
            ordered_cols = [c for c in ordered_cols_all if c not in done_cols]
            row_mask = base_mask & (~DO.df["state"].isin(TERMINAL_STATES))
            skip_cols = done_cols

        data: dict[str, list[dict]] = {c: [] for c in ordered_cols}
        for _, row in DO.df[row_mask].iterrows():
            raw_col = str(row.get("board_column") or "")
            col = _canonical_column_name(raw_col, ordered_cols_all)
            if col in skip_cols:
                continue  # surfaced via the Done drop-zone instead
            data.setdefault(col, []).append(row.to_dict())

        return data

    def _done_target_column(cust: str, wtype: str) -> str | None:
        """The canonical Done-token column name to drop items onto, if any."""
        if not cust:
            return None
        for col in _column_order(cust, wtype):
            if _col_norm(col) in DONE_TOKENS:
                return col
        return None

    def _done_items(cust: str, wtype: str) -> tuple[list[dict], int]:
        """Return (most-recent DONE_COLUMN_LIMIT done items, total done count).

        Includes terminal-state items (e.g. Closed), which are otherwise hidden
        from the regular board columns — this is the only place they're shown.
        """
        if DO is None or DO.df is None or not cust:
            return [], 0
        base_mask = (DO.df["type"] == wtype) & (DO.df["customer_name"] == cust)
        done_mask = base_mask & DO.df["board_column"].apply(
            lambda v: _col_norm(v) in DONE_TOKENS
        )
        done_df = DO.df[done_mask]
        total = len(done_df)
        if "changed_date" in done_df.columns:
            done_df = done_df.sort_values("changed_date", ascending=False)
        recent = [row.to_dict() for _, row in done_df.head(DONE_COLUMN_LIMIT).iterrows()]
        return recent, total

    async def _reload_board_data(show_notify: bool = False, notify_msg: str = ""):
        if DO is None:
            return
        ui_state["loading"] = True
        render_board.refresh()
        await DO.load_df()
        parent_label_cache.clear()
        ui_state["loading"] = False
        render_board.refresh()
        render_done_zone.refresh()
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
            customer_name=customer,
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

        # Optimistic in-memory update, then reload from DB.
        # Scoped by customer — work item IDs are only unique per organization.
        if DO.df is not None:
            row_mask = (DO.df["id"] == item_id) & (DO.df["customer_name"] == customer)
            DO.df.loc[row_mask, "board_column"] = target_col
            DO.df.loc[row_mask, "board_column_done"] = 0
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
        """Open the full DevOps update dialog for the clicked card."""
        async def _after():
            await _reload_board_data(show_notify=False)

        await open_work_item_dialog(
            core, row, on_success=_after,
            priority_colors=PRIORITY_COLORS, priority_labels=PRIORITY_LABELS,
        )

    # ── add-item dialog (shared, page-independent — see devops_forms) ─────────
    async def _open_add_dialog(preset_type: str | None = None,
                               preset_parent: str | None = None):
        """Open the shared add form seeded with the board's current customer /
        type. `preset_type`/`preset_parent` come from the hierarchy's ＋ button
        (add a child under the focused node)."""

        async def _after():
            await _reload_board_data(show_notify=False)
            # When adding from the hierarchy view, redraw its graph so the new
            # node appears immediately.
            if view_state["view"] == "hierarchy":
                await hier.refresh()

        await open_add_work_item_dialog(
            core,
            preset_customer=filter_state.get("customer"),
            preset_type=preset_type or filter_state.get("type", "User Story"),
            preset_parent=preset_parent,
            on_success=_after,
        )

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

        # Tint each card's left edge with the customer's indicator colour.
        _ccolor = cust_colors.get(str(row.get("customer_name") or ""))
        _card_style = "padding: 0.5rem 0.65rem;"
        if _ccolor:
            _card_style += f" border-left: 3px solid {_ccolor};"
        with (
            ui.card()
            .classes("board-card w-full rounded-md")
            .style(_card_style)
            .props("flat draggable=true")
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
                ui.label(f"#{item_id}").classes(f"text-xs text-{muted} shrink-0")
                ui.space()
                # Show a "Done" chip only when the item is in the done sub-state
                if board_column_done:
                    ui.badge("✓ Done").props("color=positive rounded").classes("text-xs shrink-0")

            ui.label(title).classes("text-sm").style(
                "word-break:break-word; white-space:normal; line-height:1.3; margin-top:2px;"
            )
            if parent_label:
                with ui.row().classes("items-center gap-1").style("margin-top:3px;"):
                    ui.icon("account_tree", size="12px").classes(f"text-{muted} shrink-0")
                    ui.label(parent_label).classes(f"text-xs text-{muted}").style(
                        "overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:200px;"
                    )
            if assigned:
                ui.label(f"👤 {assigned}").classes(f"text-xs text-{muted}").style("margin-top:3px;")

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
                    with (
                        ui.card()
                        .classes("board-col rounded-md gap-2")
                        .style(BOARD_COLUMN_STYLE)
                        .props("flat")
                    ):
                        ui.skeleton("text", width="70%").classes("mb-2")
                        ui.separator().classes(helpers.UI_STYLES.get_layout_classes("divider_row"))
                        for _ in range(3):
                            ui.skeleton("rect", width="100%", height="72px")
            return

        if not cust:
            with ui.column().classes("items-center justify-center w-full").style("padding: 4rem;"):
                ui.icon("view_kanban", size="xl").classes(f"text-{muted}")
                ui.label("No customers with tracker data available.").classes(f"text-{muted} mt-2")
            return

        data = _board_data()
        if not data:
            with ui.column().classes("items-center justify-center w-full").style("padding: 4rem;"):
                ui.icon("inbox", size="xl").classes(f"text-{muted}")
                ui.label(
                    f"No active {filter_state['type']} items for {cust}."
                ).classes(f"text-{muted} mt-2")
            return

        with ui.row().classes("gap-3 items-start flex-nowrap").style(COLUMNS_ROW_STYLE):
            for col_name, cards in data.items():
                with (
                    ui.card()
                    .classes("board-col rounded-md gap-2")
                    .style(BOARD_COLUMN_STYLE)
                    .props("flat")
                ) as col_el:
                    # Column header — consistent with the app's card headers
                    # (semibold white title + subtle count, then a themed divider).
                    with ui.row().classes("items-center gap-2 w-full").style("padding: 0.1rem 0.2rem 0.3rem;"):
                        ui.label(col_name).classes("text-base font-semibold text-white flex-1 truncate")
                        ui.badge(str(len(cards))).props("color=grey-8 rounded").classes("text-xs")

                    ui.separator().classes(helpers.UI_STYLES.get_layout_classes("divider_row"))

                    # Drop zone on the column container
                    col_el.on("dragover.prevent", lambda e: None)
                    col_el.on("dragenter", lambda e, c=col_el: c.classes(add="wt-board-col-hover"))
                    col_el.on("dragleave", lambda e, c=col_el: c.classes(remove="wt-board-col-hover"))

                    def _make_drop_handler(cn, c):
                        async def handler(e):
                            await _handle_drop(cn, c)
                        return handler

                    col_el.on("drop", _make_drop_handler(col_name, col_el))

                    # Cards, with a faint hairline between them for separation.
                    with ui.column().classes("w-full").style("gap: 0.45rem;"):
                        for idx, card_row in enumerate(cards):
                            if idx:
                                ui.element("div").classes("w-full").style(
                                    "border-top: 1px solid rgba(255, 255, 255, 0.08);"
                                )
                            _render_card(card_row)

    # ── Done drop-zone (persistent, outside the scrollable column area) ────────
    async def _open_done_popup(items: list[dict]):
        """Read-only popup of the most recently completed items."""
        with ui.dialog() as dlg, ui.card().classes("rounded-lg").style(
            "min-width: 320px; max-width: 420px; max-height: 70vh;"
            "overflow-y: auto; padding: 0.75rem;"
        ):
            with ui.row().classes("items-center gap-2 w-full"):
                ui.icon("done_all", size="18px").classes("text-positive shrink-0")
                ui.label("Recently Completed").classes("text-sm font-semibold flex-1")
                ui.button(icon="close", on_click=dlg.close).props("flat dense round color=grey-6")
            ui.label(f"Showing the {DONE_COLUMN_LIMIT} most recently changed items").classes(
                "text-xs text-" + muted + " mb-1"
            )
            ui.separator().classes("opacity-20 mb-2")
            if not items:
                ui.label("No completed items yet.").classes(f"text-{muted} text-sm")
            else:
                with ui.column().classes("w-full").style("gap: 0.45rem;"):
                    for idx, row in enumerate(items):
                        if idx:
                            ui.element("div").classes("w-full").style(
                                "border-top: 1px solid rgba(255, 255, 255, 0.08);"
                            )
                        _render_card(row)
        dlg.open()

    @ui.refreshable
    def render_done_zone():
        cust = filter_state["customer"]
        wtype = filter_state["type"]
        target_col = _done_target_column(cust, wtype)
        recent, total = _done_items(cust, wtype) if target_col else ([], 0)

        with (
            ui.card()
            .classes("board-col rounded-md gap-1 items-center justify-center")
            .style(DONE_ZONE_STYLE)
            .props("flat")
        ) as zone:
            ui.icon("done_all", size="22px").classes(
                "text-positive" if target_col else f"text-{muted}"
            )
            ui.label("Done").classes(f"text-xs font-semibold text-{muted}")
            ui.badge(str(total)).props(
                f"color={'green-7' if target_col else 'grey-7'} rounded"
            )

            if target_col:
                zone.classes("cursor-pointer")
                zone.tooltip("Drop an item here to mark it Done, or click to view recent ones")
                zone.on("dragover.prevent", lambda e: None)
                zone.on("dragenter", lambda e, z=zone: z.classes(add="wt-board-col-hover"))
                zone.on("dragleave", lambda e, z=zone: z.classes(remove="wt-board-col-hover"))

                async def _on_done_drop(e, tc=target_col):
                    await _handle_drop(tc, zone)

                async def _on_done_click(e, items=recent):
                    await _open_done_popup(items)

                zone.on("drop", _on_done_drop)
                zone.on("click", _on_done_click)
            else:
                zone.tooltip("No Done column found for this board")

    # ── toolbar ────────────────────────────────────────────────────────────────
    async def _on_type_chip_click(t: str):
        filter_state["type"] = t
        render_board.refresh()
        render_done_zone.refresh()
        render_type_chips.refresh()

    @ui.refreshable
    def render_type_chips():
        segmented_chips(
            core.theme,
            [(t, t) for t in _work_item_types(filter_state["customer"])],
            filter_state["type"],
            _on_type_chip_click,
        )

    def _on_search(e):
        filter_state["search"] = (e.value or "").strip()
        render_board.refresh()

    def _on_include_done(e):
        filter_state["include_done"] = bool(e.value)
        app.storage.user["board_include_done"] = filter_state["include_done"]
        render_board.refresh()

    async def _on_refresh():
        await _reload_board_data(
            show_notify=True, notify_msg="Board refreshed from local cache"
        )

    # ── view toggle (Board / Hierarchy) ────────────────────────────────────────
    def _on_view_change(value):
        if value == view_state["view"]:
            return
        view_state["view"] = value
        app.storage.user["devops_view"] = value
        if value == "hierarchy":
            hier.set_customer(filter_state["customer"])
        render_view_toggle.refresh()
        render_view_controls.refresh()
        render_view_actions.refresh()
        _apply_view()

    @ui.refreshable
    def render_view_toggle():
        segmented_chips(
            core.theme,
            [("board", "Board"), ("hierarchy", "Hierarchy")],
            view_state["view"],
            _on_view_change,
        )

    @ui.refreshable
    def render_view_controls():
        if view_state["view"] == "board":
            with toolbar_group(core.theme, "Type", divider_after=True):
                render_type_chips()
            with toolbar_group(core.theme, "Search", divider_after=False):
                search_input = ui.input(
                    placeholder="title, #id, assignee, parent…",
                    value=filter_state.get("search", ""),
                    on_change=_on_search,
                ).props("dense outlined clearable debounce=250").classes(
                    "w-60 shrink-0"
                )
                with search_input.add_slot("prepend"):
                    ui.icon("search").classes("text-sm")
                ui.switch(
                    "Incl. done",
                    value=filter_state.get("include_done", False),
                    on_change=_on_include_done,
                ).props("dense").classes("shrink-0").tooltip(
                    "Also search Done / closed items (shown in their columns while "
                    "a search is active)"
                )
        else:
            hier.render_controls()

    async def _open_add_from_hierarchy():
        """＋ in the hierarchy view: when a node is focused, pre-select it as the
        parent and default the new item to the next level down (Epic → Feature,
        Feature → User Story). Whole-tree or leaf focus opens a plain add."""
        focus = hier.get_focus()
        levels = list(
            DO.type_hierarchy(filter_state["customer"])
            if DO is not None else DEFAULT_TYPE_HIERARCHY
        )
        child_type = None
        if focus and focus["type"] in levels:
            idx = levels.index(focus["type"])
            if idx + 1 < len(levels):
                child_type = levels[idx + 1]
        if focus and child_type:
            await _open_add_dialog(
                preset_type=child_type, preset_parent=focus["display_name"]
            )
        else:
            await _open_add_dialog()

    @ui.refreshable
    def render_view_actions():
        if view_state["view"] == "board":
            async def _open_add_plain():
                # Zero-arg wrapper — a bare _open_add_dialog reference would let
                # NiceGUI pass the click event into preset_type.
                await _open_add_dialog()

            ui.button(icon="refresh", on_click=_on_refresh).props(
                "flat dense color=white"
            ).tooltip("Reload from local DB (no API call)")
            ui.button(icon="add", on_click=_open_add_plain).props(
                "flat dense color=white"
            ).tooltip("Add new work item")
        else:
            hier.render_zoom_controls()
            ui.button(icon="refresh", on_click=hier.refresh).props(
                "flat dense color=white"
            ).tooltip("Reload from local cache")
            ui.button(icon="add", on_click=_open_add_from_hierarchy).props(
                "flat dense color=white"
            ).tooltip(
                "Add work item — created under the focused item when a focus "
                "is selected"
            )

    with toolbar(core.theme):
        with toolbar_group(core.theme, divider_after=True):
            ui.icon("view_kanban", size="md").classes(f"text-{core.theme.get('accent')}")
            ui.label("Board").classes(helpers.UI_STYLES.get_layout_classes("page_title"))

        if len(customer_names) > 1:
            with toolbar_group(core.theme, "Customer", divider_after=True):
                with (
                    ui.tabs(value=filter_state["customer"])
                    .props(
                        f'horizontal dense active-color="{core.theme.get("accent")}" '
                        f'indicator-color="{core.theme.get("accent")}"'
                    )
                    .classes(helpers.UI_STYLES.get_layout_classes("tab_label"))
                ) as cust_tabs:
                    for c in customer_names:
                        with ui.tab(c, label=""):
                            with ui.row().classes("items-center gap-1.5 no-wrap"):
                                if cust_colors.get(c):
                                    ui.element("div").style(
                                        f"width:9px; height:9px; border-radius:50%;"
                                        f" flex:0 0 auto; background:{cust_colors[c]};"
                                    )
                                ui.label(c)

                async def _on_customer_change(e):
                    filter_state["customer"] = e.value
                    app.storage.user["devops_customer"] = e.value
                    # Trackers differ in type names (User Story vs Story) — a
                    # stale type from the previous customer would blank the
                    # board, so snap to the new tracker's preferred level.
                    types = _work_item_types(e.value)
                    if filter_state["type"] not in types:
                        filter_state["type"] = (
                            DO.preferred_type(e.value) if DO is not None else types[0]
                        )
                    render_type_chips.refresh()
                    render_board.refresh()
                    render_done_zone.refresh()
                    hier.set_customer(e.value)

                cust_tabs.on_value_change(_on_customer_change)
        elif customer_names:
            with toolbar_group(core.theme, "Customer", divider_after=True):
                ui.label(customer_names[0]).classes("text-white text-sm shrink-0")

        with toolbar_group(core.theme, "View", divider_after=True):
            render_view_toggle()

        render_view_controls()

        ui.space()

        render_view_actions()

    # Reload the board when a DevOps sync completes elsewhere (settings page
    # emits "devops_refreshed" after manual syncs; the background tracker
    # init emits it when the connections land).
    page_client = context.client

    def _on_devops_refreshed(**_):
        # Page built BEFORE the background init finished (engine/df missing)?
        # The customer tabs and closures can't be rebuilt by a soft refresh —
        # reload this page once, now that data exists (the automatic version
        # of the manual F5 that used to be needed).
        eng = core.devops_engine
        if (DO is None or not customer_names) and eng is not None:
            if eng.df is not None and not eng.df.empty:
                try:
                    if board_container.id in page_client.elements:
                        with page_client:
                            ui.navigate.reload()
                except Exception:
                    pass  # page gone or client disconnected — nothing to do
                return
        asyncio.create_task(_reload_board_data(show_notify=False))

    core.event_bus.register_unique(
        "devops_refreshed", _on_devops_refreshed, key="board_page"
    )

    # ── board area: scrollable columns + persistent Done drop-zone ─────────────
    # No single big wrapping card here — like time_tracking's entity_card_shell
    # cards or add_data's forms, each column (and the Done zone) is its own
    # ui.card sitting directly on the page background.
    # Board content lives in one container, the embedded Hierarchy in another.
    # The view toggle shows one and hides the other (both are position:fixed via
    # wt-page-content, so they occupy the same area). Hierarchy renders lazily on
    # first switch.
    board_container = (
        ui.row()
        .classes("wt-page-content w-full flex-nowrap items-stretch")
        .style("box-sizing: border-box; padding: 0.5rem 1rem; gap: 0.5rem;")
    )
    with board_container:
        with ui.element("div").classes("overflow-x-auto overflow-y-auto flex-1 min-w-0"):
            # Full width lets columns (flex-grow, see BOARD_COLUMN_STYLE) fill the
            # available space when there are few of them; flex-nowrap + overflow-x-auto
            # above still kicks in for natural horizontal scrolling once columns no
            # longer fit.
            with ui.element("div").style("width: 100%;"):
                render_board()

        # Outside the scrollable area so it stays visible regardless of horizontal
        # scroll position — a permanent target for dragging items to Done.
        render_done_zone()

    hier_container = (
        ui.card()
        .props("flat")
        .classes("wt-page-content mx-4 my-2 rounded-md flex flex-col hidden")
        .style("width: calc(100% - 2rem); box-sizing: border-box; overflow-y: hidden;")
    )
    _hier_rendered = {"done": False}

    def _apply_view():
        if view_state["view"] == "board":
            board_container.classes(remove="hidden")
            hier_container.classes(add="hidden")
        else:
            board_container.classes(add="hidden")
            hier_container.classes(remove="hidden")
            if not _hier_rendered["done"]:
                _hier_rendered["done"] = True
                with hier_container:
                    hier.render_content()

    _apply_view()
