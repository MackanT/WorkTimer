"""
DevOps Hierarchy page — the Epic → Feature → User Story tree as a Mermaid graph.

Reads the same locally-cached DevOps dataframe the board uses (parent_id gives
the hierarchy) and renders it top-down. Read-only. Supports zoom/pan (the graph
renders at natural size in a scrollable viewport) and a Focus selector to drill
into a single Epic or Feature's subtree.
"""

import asyncio
import re
from collections import deque

import pandas as pd
from nicegui import app, ui

from ..core.app import AppCore
from ..helpers import UI_STYLES
from ..ui.devops_forms import open_work_item_dialog
from ..ui.elements import page_card, segmented_chips, toolbar, toolbar_group

# Per-client node-click handler, keyed by client id. A module dict (not
# app.storage.client, which copies) so the JS-emitted click routes to the
# current page render; cleaned up on disconnect.
_hier_click_targets: dict = {}

_TERMINAL_STATES = {"Closed", "Removed"}
_DONE_STATES = {"Resolved", "Closed"}
_TYPE_CLASS = {"Epic": "epic", "Feature": "feature", "User Story": "story"}

# Legend colours mirror the classDefs in build_mermaid().
LEGEND = (
    ("Epic", "#6d28d9"),
    ("Feature", "#1d4ed8"),
    ("User Story", "#0f766e"),
    ("Done", "#334155"),
)


def _story_progress_map(df: pd.DataFrame, customer: str) -> dict:
    """Map each work item id -> (done_stories, total_stories) over its whole
    subtree, computed from ALL states (so rollups count hidden/closed items too).
    """
    full = df[df["customer_name"] == customer]
    children: dict[int, list[int]] = {}
    info: dict[int, tuple] = {}
    for _, r in full.iterrows():
        rid = int(r["id"])
        info[rid] = (str(r.get("type") or ""), str(r.get("state") or ""))
        pid = r.get("parent_id")
        if pid is not None and not pd.isna(pid):
            children.setdefault(int(pid), []).append(rid)

    progress: dict[int, tuple] = {}
    for node_id in info:
        done = total = 0
        stack = list(children.get(node_id, []))
        seen = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            typ, st = info.get(cur, ("", ""))
            if typ == "User Story" and st != "Removed":
                total += 1
                if st in _DONE_STATES:
                    done += 1
            stack.extend(children.get(cur, []))
        progress[node_id] = (done, total)
    return progress

# Passed to ui.mermaid:
#  - useMaxWidth:false -> render at natural (readable) size in the scroll viewport
#  - lineColor -> light edges, visible on the dark card
#  - htmlLabels:false -> render node text as native SVG <text> instead of HTML in
#    a <foreignObject>. foreignObject labels blank out unpredictably depending on
#    node position (worse under the CSS `zoom` we apply), which left some boxes
#    empty even though their label text was fine. SVG text renders reliably.
MERMAID_CONFIG = {
    "htmlLabels": False,
    "themeVariables": {"lineColor": "#94a3b8", "fontSize": "14px"},
    "flowchart": {
        "useMaxWidth": False,
        "htmlLabels": False,
        "nodeSpacing": 45,
        "rankSpacing": 55,
    },
}

# "[ref:… | kst:… pnr:…]" tags on work items are metadata noise AND break the
# Mermaid label — strip the whole bracketed segment first.
_METADATA_TAG_RE = re.compile(r"\[[^\]]*\]")

# Whitelist the rest: keep letters (incl. Nordic via \w), digits, whitespace and
# a tiny safe punctuation set. Everything else becomes a space. Many characters
# break a quoted Mermaid label even inside quotes — () [] {} are shape
# delimiters, | is an edge label, <>/"/` are markup, and /, +, %, ?, ! and
# friends also trip the parser — so a whitelist is the only reliable rule.
_LABEL_SAFE_RE = re.compile(r"[^\w\s.,:\-]", re.UNICODE)


def _sanitize_label(text) -> str:
    """Make a title safe inside a Mermaid `["..."]` node and keep it short."""
    text = str(text or "").strip()
    text = _METADATA_TAG_RE.sub("", text)  # drop "[ref:… | kst:…]" tags entirely
    text = text.replace("&", " and ")  # keep the common ampersand as a word
    text = _LABEL_SAFE_RE.sub(" ", text)  # whitelist everything else out
    text = re.sub(r"\s+", " ", text).strip()  # collapse whitespace left behind
    if len(text) > 42:
        text = text[:39].rstrip() + "..."  # <= 42 chars total
    return text


def _descendants(sub: pd.DataFrame, root_id: int) -> set:
    """Return root_id plus every transitive child id within `sub`."""
    children: dict[int, list[int]] = {}
    for _, r in sub.iterrows():
        pid = r.get("parent_id")
        if pid is None or pd.isna(pid):
            continue
        children.setdefault(int(pid), []).append(int(r["id"]))

    keep: set[int] = set()
    queue = deque([int(root_id)])
    while queue:
        cur = queue.popleft()
        if cur in keep:
            continue
        keep.add(cur)
        queue.extend(children.get(cur, []))
    return keep


def _filtered(df: pd.DataFrame, customer: str, include_closed: bool) -> pd.DataFrame:
    sub = df[df["customer_name"] == customer]
    if not include_closed:
        sub = sub[~sub["state"].isin(_TERMINAL_STATES)]
    return sub


def build_mermaid(
    df: pd.DataFrame,
    customer: str,
    include_closed: bool = False,
    focus_id: int | None = None,
    direction: str = "TD",
) -> str:
    """Return a Mermaid flowchart of one customer's work-item hierarchy.

    Nodes are coloured by type. An item whose parent isn't in the rendered set
    (filtered out, or a non-Epic/Feature/Story parent) becomes a root. When
    focus_id is given, only that item and its descendants are shown. `direction`
    is a Mermaid flowchart direction (TD = top-down, LR = left-right). Returns an
    empty string when there is nothing to show.
    """
    if df is None or df.empty or not customer:
        return ""

    sub = _filtered(df, customer, include_closed)
    if focus_id is not None and not sub.empty:
        keep = _descendants(sub, focus_id)
        sub = sub[sub["id"].astype(int).isin(keep)]
    if sub.empty:
        return ""

    present = {int(r["id"]) for _, r in sub.iterrows()}
    progress = _story_progress_map(df, customer)

    header = [
        f"flowchart {direction}",
        # Borderless (stroke matches fill); nodes use the round-edge shape below.
        "classDef epic fill:#6d28d9,stroke:#6d28d9,color:#fff;",
        "classDef feature fill:#1d4ed8,stroke:#1d4ed8,color:#fff;",
        "classDef story fill:#0f766e,stroke:#0f766e,color:#fff;",
        "classDef done fill:#334155,stroke:#334155,color:#cbd5e1;",
    ]

    node_lines = []
    for _, r in sub.iterrows():
        wid = int(r["id"])
        title = _sanitize_label(r.get("title"))
        label = f"#{wid}: {title}" if title else f"#{wid}"
        item_type = str(r.get("type"))
        # Progress rollup on Epics/Features ("2 of 5 done"). No / or ( ) — those
        # break Mermaid labels; only whitelist-safe characters here.
        if item_type in ("Epic", "Feature"):
            done, total = progress.get(wid, (0, 0))
            if total:
                label += f"  {done} of {total} done"
        # Round-edge shape n("..") — softer, matches the app's rounded cards.
        node_lines.append(f'n{wid}("{label}")')
        # Done items grey out; everything else is coloured by type.
        state = str(r.get("state") or "")
        cls = "done" if state in _DONE_STATES else _TYPE_CLASS.get(item_type)
        if cls:
            node_lines.append(f"class n{wid} {cls};")

    edge_lines = []
    for _, r in sub.iterrows():
        pid = r.get("parent_id")
        if pid is None or pd.isna(pid):
            continue
        pid = int(pid)
        if pid in present:
            edge_lines.append(f"n{pid} --> n{int(r['id'])}")

    lines = header + node_lines + edge_lines
    if edge_lines:
        # Thicker, lighter links (belt-and-suspenders with themeVariables.lineColor).
        lines.append("linkStyle default stroke:#94a3b8,stroke-width:2px;")
    return "\n".join(lines)


def default_focus_id(
    df: pd.DataFrame, customer: str, include_closed: bool = False, threshold: int = 60
) -> int | None:
    """For a large tree, open focused on the first Epic instead of the whole
    scatter of every node. Small trees (<= threshold nodes) open whole (None).
    """
    if df is None or df.empty or not customer:
        return None
    sub = _filtered(df, customer, include_closed)
    if len(sub) <= threshold:
        return None
    epics = sub[sub["type"] == "Epic"].sort_values("id")
    if epics.empty:
        return None
    return int(epics.iloc[0]["id"])


def focus_options(df: pd.DataFrame, customer: str, include_closed: bool = False) -> dict:
    """Options for the Focus selector: {value: label}, Epics then Features.

    Value "" means the whole tree; other values are the work-item id as a string.
    """
    opts = {"": "Whole tree"}
    if df is None or df.empty or not customer:
        return opts

    sub = _filtered(df, customer, include_closed)
    parents = sub[sub["type"].isin(["Epic", "Feature"])].copy()
    if parents.empty:
        return opts
    parents["_ord"] = parents["type"].map({"Epic": 0, "Feature": 1})
    parents = parents.sort_values(["_ord", "id"])
    for _, r in parents.iterrows():
        wid = int(r["id"])
        opts[str(wid)] = f"{r['type']} #{wid}: {_sanitize_label(r.get('title'))}"
    return opts


async def hierarchy_page():
    """DevOps hierarchy — Mermaid tree of the selected customer's work items.

    Note: No @ui.page decorator — accessed via SPA sub_pages in root.py.
    """
    core = await AppCore.get_or_initialize()
    DO = core.devops_engine

    customer_names: list[str] = []
    if DO is not None and DO.df is not None:
        customer_names = sorted(DO.df["customer_name"].dropna().unique().tolist())

    state = {
        "customer": customer_names[0] if customer_names else None,
        "show_closed": False,
        "focus_id": None,
        "zoom": 1.0,
        "direction": "TD",
    }
    # Large trees would otherwise open as an unreadable 170-node scatter — start
    # focused on the first Epic (a tight, complete subtree).
    if DO is not None and DO.df is not None and state["customer"]:
        state["focus_id"] = default_focus_id(
            DO.df, state["customer"], state["show_closed"]
        )

    def _apply_zoom():
        # CSS `zoom` scales the graph AND its layout box, so the scroll viewport
        # adapts (works in Chromium/Edge; Firefox 126+).
        ui.run_javascript(
            f"document.querySelectorAll('.wt-hier-graph')"
            f".forEach(e => e.style.zoom = {state['zoom']});"
        )

    @ui.refreshable
    def render_graph():
        if DO is None or DO.df is None or not state["customer"]:
            with ui.column().classes("items-center justify-center w-full").style(
                "padding: 4rem;"
            ):
                ui.icon("account_tree", size="xl").classes("text-grey-6")
                ui.label("No DevOps data available.").classes("text-grey-5 mt-2")
            return

        code = build_mermaid(
            DO.df,
            state["customer"],
            include_closed=state["show_closed"],
            focus_id=state["focus_id"],
            direction=state["direction"],
        )
        if not code:
            with ui.column().classes("items-center justify-center w-full").style(
                "padding: 4rem;"
            ):
                ui.icon("inbox", size="xl").classes("text-grey-6")
                ui.label(
                    f"No work items to show for {state['customer']}."
                ).classes("text-grey-5 mt-2")
            return

        # Natural-size graph (useMaxWidth:false) inside the scroll viewport, with
        # the current zoom applied. inline-block so the box sizes to the SVG.
        with ui.element("div").classes("wt-hier-graph").style(
            f"zoom: {state['zoom']}; display: inline-block;"
        ):
            ui.mermaid(code, config=MERMAID_CONFIG)

    @ui.refreshable
    def render_focus_select():
        opts = (
            focus_options(DO.df, state["customer"], state["show_closed"])
            if (DO is not None and DO.df is not None and state["customer"])
            else {"": "Whole tree"}
        )
        value = "" if state["focus_id"] is None else str(state["focus_id"])
        if value not in opts:  # focused item no longer available (e.g. closed)
            value = ""
            state["focus_id"] = None
        sel = (
            ui.select(opts, value=value, label="Focus", with_input=True)
            .props("dense outlined")
            .classes("w-64 shrink-0")
        )

        def _on_focus(e):
            state["focus_id"] = int(e.value) if e.value else None
            render_graph.refresh()

        sel.on_value_change(_on_focus)

    # ── node click → work-item dialog ─────────────────────────────────────────
    async def _open_item_dialog(item_id: int):
        if DO is None or DO.df is None:
            return
        match = DO.df[
            (DO.df["id"] == item_id) & (DO.df["customer_name"] == state["customer"])
        ]
        if match.empty:
            return
        row = match.iloc[0].to_dict()

        async def _after():
            await DO.load_df()
            render_focus_select.refresh()
            render_graph.refresh()

        await open_work_item_dialog(core, row, on_success=_after)

    client = ui.context.client
    _hier_click_targets[client.id] = _open_item_dialog
    if not app.storage.client.get("hier_click_registered"):
        app.storage.client["hier_click_registered"] = True

        async def _dispatch(e, target=client):
            handler = _hier_click_targets.get(target.id)
            if handler:
                # The event arrives with no UI slot on the stack, so creating the
                # dialog would fail — enter the client context first (same pattern
                # the EventBus uses for cross-thread UI).
                with target:
                    await handler(int(e.args))

        ui.on("hier_node_click", _dispatch)
        client.on_disconnect(
            lambda cid=client.id: _hier_click_targets.pop(cid, None)
        )

    # ── toolbar ──────────────────────────────────────────────────────────────
    def _on_direction(value):
        state["direction"] = value
        render_direction_chips.refresh()
        render_graph.refresh()

    @ui.refreshable
    def render_direction_chips():
        segmented_chips(
            core.theme,
            [("TD", "Top-down"), ("LR", "Left-right")],
            state["direction"],
            _on_direction,
        )

    def _on_show_closed(e):
        state["show_closed"] = e.value
        # Keep the current focus (render_focus_select drops it if it's no longer
        # an available option).
        render_focus_select.refresh()
        render_graph.refresh()

    def _zoom(mult=None):
        state["zoom"] = 1.0 if mult is None else max(0.2, min(5.0, state["zoom"] * mult))
        _apply_zoom()

    async def _on_refresh():
        if DO is not None:
            await DO.load_df()
        render_focus_select.refresh()
        render_graph.refresh()

    with toolbar(core.theme):
        with toolbar_group(core.theme, divider_after=True):
            ui.icon("account_tree", size="md").classes(f"text-{core.theme.get('accent')}")
            ui.label("Hierarchy").classes(UI_STYLES.get_layout_classes("page_title"))

        if len(customer_names) > 1:
            with toolbar_group(core.theme, "Customer", divider_after=True):
                with (
                    ui.tabs(value=state["customer"])
                    .props(
                        f'horizontal dense active-color="{core.theme.get("accent")}" '
                        f'indicator-color="{core.theme.get("accent")}"'
                    )
                    .classes(UI_STYLES.get_layout_classes("tab_label"))
                ) as cust_tabs:
                    for c in customer_names:
                        ui.tab(c, label=c)

                def _on_customer_change(e):
                    state["customer"] = e.value
                    # Re-apply the large-tree default focus for the new customer.
                    state["focus_id"] = (
                        default_focus_id(DO.df, e.value, state["show_closed"])
                        if (DO is not None and DO.df is not None)
                        else None
                    )
                    render_focus_select.refresh()
                    render_graph.refresh()

                cust_tabs.on_value_change(_on_customer_change)
        elif customer_names:
            with toolbar_group(core.theme, "Customer", divider_after=True):
                ui.label(customer_names[0]).classes("text-white text-sm shrink-0")

        with toolbar_group(core.theme, "Focus", divider_after=True):
            render_focus_select()

        with toolbar_group(core.theme, "Layout", divider_after=True):
            render_direction_chips()

        with toolbar_group(core.theme, "Closed", divider_after=False):
            ui.switch(value=False, on_change=_on_show_closed).props("dense").tooltip(
                "Show closed / removed items"
            )

        ui.space()

        with ui.row().classes("items-center gap-0 shrink-0"):
            ui.button(icon="zoom_out", on_click=lambda: _zoom(0.8)).props(
                "flat dense color=white"
            ).tooltip("Zoom out")
            ui.button(icon="restart_alt", on_click=lambda: _zoom()).props(
                "flat dense color=white"
            ).tooltip("Reset zoom")
            ui.button(icon="zoom_in", on_click=lambda: _zoom(1.25)).props(
                "flat dense color=white"
            ).tooltip("Zoom in")

        ui.button(icon="refresh", on_click=_on_refresh).props(
            "flat dense color=white"
        ).tooltip("Reload from local cache")

    # ── legend + scrollable graph viewport ───────────────────────────────────
    with page_card(scrollable=False):
        with ui.row().classes("items-center gap-4 px-1 pb-1 shrink-0"):
            for lbl, color in LEGEND:
                with ui.row().classes("items-center gap-1"):
                    ui.element("div").style(
                        f"width:12px; height:12px; border-radius:3px; background:{color};"
                    )
                    ui.label(lbl).classes(
                        "text-xs " + UI_STYLES.get_layout_classes("muted_text")
                    )

        with ui.element("div").classes("w-full").style(
            "flex: 1; min-height: 0; overflow: auto;"
        ):
            render_graph()

    # Make nodes look clickable, and forward node clicks to Python. The listener
    # is delegated on document (survives graph re-renders) and idempotent via a
    # window flag; it reads the work-item id from the Mermaid node's element id.
    if not app.storage.client.get("hier_css_injected"):
        app.storage.client["hier_css_injected"] = True
        ui.add_head_html(
            "<style>"
            ".wt-hier-graph .node { cursor: pointer; }"
            # Soft drop shadow on the node shapes for a card-like depth.
            ".wt-hier-graph .node rect { filter: drop-shadow(0 1px 3px rgba(0,0,0,0.35)); }"
            "</style>"
        )
    ui.run_javascript(
        """
        if (!window._wtHierClick) {
            window._wtHierClick = true;
            document.addEventListener('click', function (e) {
                if (!e.target.closest('.wt-hier-graph')) return;
                var node = e.target.closest('.node');
                if (!node) return;
                var m = (node.id || '').match(/n(\\d+)/);
                if (m) emitEvent('hier_node_click', parseInt(m[1], 10));
            }, true);
        }
        """
    )
