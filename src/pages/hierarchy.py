"""
DevOps Hierarchy page — the Epic → Feature → User Story tree as a Mermaid graph.

Reads the same locally-cached DevOps dataframe the board uses (parent_id gives
the hierarchy) and renders it top-down. Read-only. Supports zoom/pan (the graph
renders at natural size in a scrollable viewport) and a Focus selector to drill
into a single Epic or Feature's subtree.
"""

import re
from collections import deque

import pandas as pd
from nicegui import ui

from ..core.app import AppCore
from ..helpers import UI_STYLES
from ..ui.elements import page_card, toolbar

_TERMINAL_STATES = {"Closed", "Removed"}
_TYPE_CLASS = {"Epic": "epic", "Feature": "feature", "User Story": "story"}

# Legend colours mirror the classDefs in build_mermaid().
LEGEND = (("Epic", "#6d28d9"), ("Feature", "#1d4ed8"), ("User Story", "#0f766e"))

# Passed to ui.mermaid: render at natural size and use a light edge colour so the
# arrows are visible on the dark card (default lineColor is near-invisible).
MERMAID_CONFIG = {
    "themeVariables": {"lineColor": "#94a3b8", "fontSize": "14px"},
    "flowchart": {"useMaxWidth": False, "nodeSpacing": 45, "rankSpacing": 55},
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

    header = [
        f"flowchart {direction}",
        "classDef epic fill:#6d28d9,stroke:#a78bfa,color:#fff;",
        "classDef feature fill:#1d4ed8,stroke:#60a5fa,color:#fff;",
        "classDef story fill:#0f766e,stroke:#2dd4bf,color:#fff;",
    ]

    node_lines = []
    for _, r in sub.iterrows():
        wid = int(r["id"])
        title = _sanitize_label(r.get("title"))
        label = f"#{wid}: {title}" if title else f"#{wid}"
        node_lines.append(f'n{wid}["{label}"]')
        cls = _TYPE_CLASS.get(str(r.get("type")))
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
        sel = (
            ui.select(opts, value="", label="Focus", with_input=True)
            .props("dense outlined")
            .classes("w-64 shrink-0")
        )

        def _on_focus(e):
            state["focus_id"] = int(e.value) if e.value else None
            render_graph.refresh()

        sel.on_value_change(_on_focus)

    # ── toolbar ──────────────────────────────────────────────────────────────
    with toolbar(core.theme):
        with ui.row().classes("items-center gap-3 w-full flex-nowrap"):
            ui.label("Hierarchy").classes("text-white font-bold shrink-0")

            if len(customer_names) > 1:
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
                    state["focus_id"] = None  # focus options are per-customer
                    render_focus_select.refresh()
                    render_graph.refresh()

                cust_tabs.on_value_change(_on_customer_change)
            elif customer_names:
                ui.label(customer_names[0]).classes("text-white text-sm shrink-0")

            ui.space()

            render_focus_select()

            def _on_show_closed(e):
                state["show_closed"] = e.value
                state["focus_id"] = None
                render_focus_select.refresh()
                render_graph.refresh()

            ui.switch("Show closed", value=False, on_change=_on_show_closed).props(
                "dense"
            ).classes("text-white shrink-0")

            def _on_direction(e):
                state["direction"] = e.value
                render_graph.refresh()

            ui.toggle(
                {"TD": "Top-down", "LR": "Left-right"},
                value="TD",
                on_change=_on_direction,
            ).props("dense no-caps unelevated").classes("shrink-0")

            # zoom controls
            def _zoom(mult=None):
                if mult is None:
                    state["zoom"] = 1.0
                else:
                    state["zoom"] = max(0.2, min(5.0, state["zoom"] * mult))
                _apply_zoom()

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

            async def _on_refresh():
                if DO is not None:
                    await DO.load_df()
                render_focus_select.refresh()
                render_graph.refresh()

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
