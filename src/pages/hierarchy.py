"""
DevOps Hierarchy page — the Epic → Feature → User Story tree as a Mermaid graph.

Reads the same locally-cached DevOps dataframe the board uses (parent_id gives
the hierarchy) and renders it top-down. Purely a read-only visualization.
"""

import pandas as pd
from nicegui import ui

from ..core.app import AppCore
from ..helpers import UI_STYLES
from ..ui.elements import page_card, toolbar

_TERMINAL_STATES = {"Closed", "Removed"}
_TYPE_CLASS = {"Epic": "epic", "Feature": "feature", "User Story": "story"}


def _sanitize_label(text) -> str:
    """Make a title safe inside a Mermaid `["..."]` node and keep it short."""
    text = str(text or "").strip()
    # Double quotes close the node label; angle brackets can be read as HTML.
    text = text.replace('"', "'").replace("<", "(").replace(">", ")").replace("\n", " ")
    if len(text) > 42:
        text = text[:41].rstrip() + "…"
    return text


def build_mermaid(df: pd.DataFrame, customer: str, include_closed: bool = False) -> str:
    """Return a Mermaid flowchart of one customer's work-item hierarchy.

    Nodes are coloured by type. An item whose parent isn't in the rendered set
    (filtered out, or a non-Epic/Feature/Story parent) becomes a root. Returns
    an empty string when there is nothing to show.
    """
    if df is None or df.empty or not customer:
        return ""

    sub = df[df["customer_name"] == customer]
    if not include_closed:
        sub = sub[~sub["state"].isin(_TERMINAL_STATES)]
    if sub.empty:
        return ""

    present = {int(r["id"]) for _, r in sub.iterrows()}

    lines = [
        "flowchart TD",
        "classDef epic fill:#6d28d9,stroke:#a78bfa,color:#fff;",
        "classDef feature fill:#1d4ed8,stroke:#60a5fa,color:#fff;",
        "classDef story fill:#0f766e,stroke:#2dd4bf,color:#fff;",
    ]

    for _, r in sub.iterrows():
        wid = int(r["id"])
        title = _sanitize_label(r.get("title"))
        label = f"#{wid}: {title}" if title else f"#{wid}"
        lines.append(f'n{wid}["{label}"]')
        cls = _TYPE_CLASS.get(str(r.get("type")))
        if cls:
            lines.append(f"class n{wid} {cls};")

    for _, r in sub.iterrows():
        pid = r.get("parent_id")
        if pid is None or pd.isna(pid):
            continue
        pid = int(pid)
        if pid in present:
            lines.append(f"n{pid} --> n{int(r['id'])}")

    return "\n".join(lines)


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
    }

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
            DO.df, state["customer"], include_closed=state["show_closed"]
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

        # Wide trees scroll horizontally rather than overflowing the card.
        with ui.element("div").style("overflow-x: auto; width: 100%;"):
            ui.mermaid(code).classes("w-full")

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
                    render_graph.refresh()

                cust_tabs.on_value_change(_on_customer_change)
            elif customer_names:
                ui.label(customer_names[0]).classes("text-white text-sm shrink-0")

            ui.space()

            def _on_show_closed(e):
                state["show_closed"] = e.value
                render_graph.refresh()

            ui.switch("Show closed", value=False, on_change=_on_show_closed).props(
                "dense"
            ).classes("text-white shrink-0")

            async def _on_refresh():
                if DO is not None:
                    await DO.load_df()
                render_graph.refresh()

            ui.button(icon="refresh", on_click=_on_refresh).props(
                "flat dense color=white"
            ).tooltip("Reload from local cache")

    with page_card(scrollable=True):
        render_graph()
