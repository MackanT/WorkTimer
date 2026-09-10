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
from types import SimpleNamespace

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

# Nodes are coloured by BOARD COLUMN (in progress / on hold / new …) — the
# item type already reads from tree depth, while the column is the information
# a glance can't otherwise get. Palette cycles for customers with many columns;
# assignment is deterministic (columns sorted case-insensitively).
_COLUMN_PALETTE = (
    "#0284c7",  # sky
    "#7c3aed",  # violet
    "#059669",  # emerald
    "#d97706",  # amber
    "#db2777",  # pink
    "#0d9488",  # teal
    "#4f46e5",  # indigo
    "#ea580c",  # orange
)
_DONE_COLUMN_TOKENS = {"done", "closed", "resolved", "completed"}
_DONE_COLOR = "#334155"
_NO_COLUMN_COLOR = "#475569"


def _story_progress_map(
    df: pd.DataFrame, customer: str, count_type: str = "User Story"
) -> dict:
    """Map each work item id -> (done_stories, total_stories) over its whole
    subtree, computed from ALL states (so rollups count hidden/closed items too).
    `count_type` is the tracker's working level (Azure: User Story, Jira: Story).
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
            if typ == count_type and st != "Removed":
                total += 1
                # Done by Azure state name OR by done-token status (Jira's
                # state IS its board column, e.g. "Done").
                if st in _DONE_STATES or st.strip().lower() in _DONE_COLUMN_TOKENS:
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


def _visible_sub(df, customer, include_closed, focus_id):
    """The currently rendered slice: customer + closed filter + focus subtree.
    Shared by the graph builder and the legend so they always agree."""
    if df is None or df.empty or not customer:
        return pd.DataFrame()
    sub = _filtered(df, customer, include_closed)
    if focus_id is not None and not sub.empty:
        keep = _descendants(sub, focus_id)
        sub = sub[sub["id"].astype(int).isin(keep)]
    return sub


def _is_done_row(r) -> bool:
    """Grey-out rule: a done-ish state OR sitting in a done-token board column."""
    if str(r.get("state") or "") in _DONE_STATES:
        return True
    return str(r.get("board_column") or "").strip().lower() in _DONE_COLUMN_TOKENS


def column_styles(sub: pd.DataFrame) -> dict:
    """Ordered {board-column display name: fill colour} for the non-done columns
    present in `sub` — drives both the graph classDefs and the legend."""
    if sub is None or sub.empty:
        return {}
    seen: dict = {}  # normalised name -> display casing (first seen)
    for _, r in sub.iterrows():
        if _is_done_row(r):
            continue
        col = str(r.get("board_column") or "").strip()
        if col:
            seen.setdefault(col.lower(), col)
    ordered = [seen[k] for k in sorted(seen)]
    return {
        name: _COLUMN_PALETTE[i % len(_COLUMN_PALETTE)]
        for i, name in enumerate(ordered)
    }


def build_mermaid(
    df: pd.DataFrame,
    customer: str,
    include_closed: bool = False,
    focus_id: int | None = None,
    direction: str = "TD",
    count_type: str = "User Story",
) -> str:
    """Return a Mermaid flowchart of one customer's work-item hierarchy.

    Nodes are coloured by their board column (done items greyed out; items with
    no column in a neutral slate). An item whose parent isn't in the rendered set
    (filtered out, or a non-Epic/Feature/Story parent) becomes a root. When
    focus_id is given, only that item and its descendants are shown. `direction`
    is a Mermaid flowchart direction (TD = top-down, LR = left-right). Returns an
    empty string when there is nothing to show.
    """
    sub = _visible_sub(df, customer, include_closed, focus_id)
    if sub.empty:
        return ""

    present = {int(r["id"]) for _, r in sub.iterrows()}
    progress = _story_progress_map(df, customer, count_type)

    # Board-column colouring: one class per column present in this view.
    col_colors = column_styles(sub)
    col_class = {name.lower(): f"bc{i}" for i, name in enumerate(col_colors)}

    header = [f"flowchart {direction}"]
    # Borderless (stroke matches fill); nodes use the round-edge shape below.
    for i, color in enumerate(col_colors.values()):
        header.append(f"classDef bc{i} fill:{color},stroke:{color},color:#fff;")
    header.append(
        f"classDef nocol fill:{_NO_COLUMN_COLOR},stroke:{_NO_COLUMN_COLOR},color:#e2e8f0;"
    )
    header.append(
        f"classDef done fill:{_DONE_COLOR},stroke:{_DONE_COLOR},color:#cbd5e1;"
    )

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
        # Done items grey out; everything else is coloured by its board column.
        if _is_done_row(r):
            cls = "done"
        else:
            cls = col_class.get(
                str(r.get("board_column") or "").strip().lower(), "nocol"
            )
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


def focus_options(
    df: pd.DataFrame,
    customer: str,
    include_closed: bool = False,
    parent_types: tuple = ("Epic", "Feature"),
) -> dict:
    """Options for the Focus selector: {value: label}, grouped root-first by
    `parent_types` (the tracker hierarchy's non-leaf levels).

    Value "" means the whole tree; other values are the work-item id as a string.
    """
    opts = {"": "Whole tree"}
    if df is None or df.empty or not customer:
        return opts

    sub = _filtered(df, customer, include_closed)
    parents = sub[sub["type"].isin(parent_types)].copy()
    if parents.empty:
        return opts
    parents["_ord"] = parents["type"].map(
        {t: i for i, t in enumerate(parent_types)}
    )
    parents = parents.sort_values(["_ord", "id"])
    for _, r in parents.iterrows():
        wid = int(r["id"])
        opts[str(wid)] = f"{r['type']} #{wid}: {_sanitize_label(r.get('title'))}"
    return opts


def create_hierarchy_view(core, get_customer):
    """Embeddable Hierarchy view (Mermaid tree + its toolbar controls) for the
    Board page's view toggle. `get_customer` returns the currently-selected
    customer (shared with the board). Returns a controller exposing
    render_controls(), render_zoom_controls(), render_content(), set_customer()
    and refresh()."""
    DO = core.devops_engine
    muted = core.theme.get("muted")

    state = {
        "customer": get_customer(),
        "show_closed": False,
        "focus_id": None,
        "zoom": 1.0,
        "direction": "TD",
    }
    if DO is not None and DO.df is not None and state["customer"]:
        state["focus_id"] = default_focus_id(DO.df, state["customer"], state["show_closed"])

    def _apply_zoom():
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
                ui.icon("account_tree", size="xl").classes(f"text-{muted}")
                ui.label("No tracker data available.").classes(f"text-{muted} mt-2")
            return

        code = build_mermaid(
            DO.df,
            state["customer"],
            include_closed=state["show_closed"],
            focus_id=state["focus_id"],
            direction=state["direction"],
            count_type=DO.preferred_type(state["customer"]),
        )
        if not code:
            with ui.column().classes("items-center justify-center w-full").style(
                "padding: 4rem;"
            ):
                ui.icon("inbox", size="xl").classes(f"text-{muted}")
                ui.label(
                    f"No work items to show for {state['customer']}."
                ).classes(f"text-{muted} mt-2")
            return

        with ui.element("div").classes("wt-hier-graph").style(
            f"zoom: {state['zoom']}; display: inline-block;"
        ):
            ui.mermaid(code, config=MERMAID_CONFIG)

    @ui.refreshable
    def render_legend():
        """Board-column colour legend for the currently visible slice — built
        from the same mapping build_mermaid uses, so it always matches."""
        sub = (
            _visible_sub(
                DO.df, state["customer"], state["show_closed"], state["focus_id"]
            )
            if (DO is not None and DO.df is not None)
            else pd.DataFrame()
        )
        entries = list(column_styles(sub).items())
        if not sub.empty:
            if any(
                not _is_done_row(r) and not str(r.get("board_column") or "").strip()
                for _, r in sub.iterrows()
            ):
                entries.append(("No column", _NO_COLUMN_COLOR))
            if any(_is_done_row(r) for _, r in sub.iterrows()):
                entries.append(("Done", _DONE_COLOR))
        with ui.row().classes("items-center gap-4 px-1 pb-1 shrink-0"):
            for lbl, color in entries:
                with ui.row().classes("items-center gap-1"):
                    ui.element("div").style(
                        f"width:12px; height:12px; border-radius:3px; background:{color};"
                    )
                    ui.label(lbl).classes(
                        "text-xs " + UI_STYLES.get_layout_classes("muted_text")
                    )

    def _refresh_views():
        """Graph and legend always refresh together (they share the colour map)."""
        render_legend.refresh()
        render_graph.refresh()

    @ui.refreshable
    def render_focus_select():
        opts = (
            focus_options(
                DO.df,
                state["customer"],
                state["show_closed"],
                parent_types=tuple(DO.type_hierarchy(state["customer"])[:-1]),
            )
            if (DO is not None and DO.df is not None and state["customer"])
            else {"": "Whole tree"}
        )
        value = "" if state["focus_id"] is None else str(state["focus_id"])
        if value not in opts:
            value = ""
            state["focus_id"] = None
        sel = (
            ui.select(opts, value=value, label="Focus", with_input=True)
            .props("dense outlined")
            .classes("w-64 shrink-0")
        )

        def _on_focus(e):
            state["focus_id"] = int(e.value) if e.value else None
            _refresh_views()

        sel.on_value_change(_on_focus)

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
            _refresh_views()

        await open_work_item_dialog(core, row, on_success=_after)

    client = ui.context.client
    _hier_click_targets[client.id] = _open_item_dialog
    if not app.storage.client.get("hier_click_registered"):
        app.storage.client["hier_click_registered"] = True

        async def _dispatch(e, target=client):
            handler = _hier_click_targets.get(target.id)
            if handler:
                with target:
                    await handler(int(e.args))

        ui.on("hier_node_click", _dispatch)
        client.on_disconnect(
            lambda cid=client.id: _hier_click_targets.pop(cid, None)
        )

    def _on_direction(value):
        state["direction"] = value
        render_direction_chips.refresh()
        _refresh_views()

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
        render_focus_select.refresh()
        _refresh_views()

    def _zoom(mult=None):
        state["zoom"] = 1.0 if mult is None else max(0.2, min(5.0, state["zoom"] * mult))
        _apply_zoom()

    async def _refresh():
        if DO is not None:
            await DO.load_df()
        render_focus_select.refresh()
        _refresh_views()

    def _ensure_client_js():
        if not app.storage.client.get("hier_css_injected"):
            app.storage.client["hier_css_injected"] = True
            ui.add_head_html(
                "<style>"
                ".wt-hier-graph .node { cursor: pointer; }"
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

    # -- exposed renderers --
    def render_controls():
        with toolbar_group(core.theme, "Focus", divider_after=True):
            render_focus_select()
        with toolbar_group(core.theme, "Layout", divider_after=True):
            render_direction_chips()
        with toolbar_group(core.theme, "Closed", divider_after=False):
            ui.switch(value=state["show_closed"], on_change=_on_show_closed).props(
                "dense"
            ).tooltip("Show closed / removed items")

    def render_zoom_controls():
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

    def render_content():
        render_legend()
        with ui.element("div").classes("w-full").style(
            "flex: 1; min-height: 0; overflow: auto;"
        ):
            render_graph()
        _ensure_client_js()

    def set_customer(customer):
        state["customer"] = customer
        state["focus_id"] = (
            default_focus_id(DO.df, customer, state["show_closed"])
            if (DO is not None and DO.df is not None and customer)
            else None
        )
        render_focus_select.refresh()
        _refresh_views()

    def get_focus():
        """The currently focused work item as {id, type, title, display_name},
        or None when viewing the whole tree (or the item can't be resolved).
        Lets the board's add dialog pre-parent new items under the focus."""
        if state["focus_id"] is None or DO is None or DO.df is None:
            return None
        match = DO.df[
            (DO.df["id"] == state["focus_id"])
            & (DO.df["customer_name"] == state["customer"])
        ]
        if match.empty:
            return None
        r = match.iloc[0]
        return {
            "id": int(r["id"]),
            "type": str(r["type"]),
            "title": str(r["title"] or ""),
            "display_name": str(
                r.get("display_name") or f"{r['type']}: {int(r['id'])} - {r['title']}"
            ),
        }

    return SimpleNamespace(
        render_controls=render_controls,
        render_zoom_controls=render_zoom_controls,
        render_content=render_content,
        set_customer=set_customer,
        get_focus=get_focus,
        refresh=_refresh,
        apply_zoom=_apply_zoom,
    )
