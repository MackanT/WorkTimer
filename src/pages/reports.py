"""
Reports page — a visual analytics dashboard for tracked time.

Filter by customer + period; see headline stat tiles, a daily hours trend, and
hours-by-project / hours-by-customer breakdowns (ECharts, no extra deps).
Optional billing rounding affects only the billable stat tiles / CSV — the live
Time Tracker and the charts show real tracked hours.
"""

import csv
import io
import math
from datetime import date, timedelta

import pandas as pd
from nicegui import ui, app

from ..core.app import AppCore
from .. import helpers
from ..helpers import UI_STYLES
from ..ui.elements import toolbar, toolbar_group, page_card, segmented_chips

_PERIODS = ["Day", "Week", "Month", "Year", "Custom"]

# Chart palette — single accent for single-series marks; text/grid stay in
# muted ink (never the series colour), grid recessive. Reads on the dark surface.
_ACCENT = "#38bdf8"
_ACCENT_SOFT = "rgba(56, 189, 248, 0.15)"
_AVG = "#f59e0b"  # rolling-average line — amber, CVD-safe against the sky accent
_INK = "#94a3b8"
_GRID = "rgba(148, 163, 184, 0.14)"

# A visible elevated surface for tiles/chart cards on the dark page background
# (a flat card matches the page and disappears).
_CARD = (
    "background: rgba(255,255,255,0.035); "
    "border: 1px solid rgba(255,255,255,0.09); box-shadow: none;"
)

# Per-entry duration in hours, counting a still-running timer up to "now" — so
# today's ongoing work is included, not only stopped entries (total_time is only
# written when a timer stops).
_DUR = (
    "(julianday(coalesce(end_time, datetime('now','localtime'))) "
    "- julianday(start_time)) * 24.0"
)


def _soft(color, alpha=0.15):
    """Translucent area fill derived from a #rrggbb accent."""
    c = str(color or "").lstrip("#")
    if len(c) == 6:
        try:
            r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
            return f"rgba({r}, {g}, {b}, {alpha})"
        except ValueError:
            pass
    return _ACCENT_SOFT


def round_hours(hours, increment_minutes, mode="nearest"):
    """Round `hours` (float hours) to a billing increment in minutes. mode:
    'nearest' (default), 'up', 'down'. increment 0/None → unchanged."""
    hours = float(hours or 0)
    if not increment_minutes or increment_minutes <= 0 or not hours:
        return hours
    inc = increment_minutes / 60.0
    q = hours / inc
    if mode == "up":
        q = math.ceil(q)
    elif mode == "down":
        q = math.floor(q)
    else:
        q = round(q)
    return q * inc


def compute_report_rows(raw_rows, round_minutes, mode="nearest"):
    """raw_rows: dicts {project, hours, cost} → billable rows with rounded hours
    and an amount scaled by the same ratio (effective rate preserved)."""
    rows = []
    for r in raw_rows:
        raw_h = float(r.get("hours") or 0)
        raw_c = float(r.get("cost") or 0)
        rate = (raw_c / raw_h) if raw_h else 0.0
        billed_h = round_hours(raw_h, round_minutes, mode)
        rows.append(
            {
                "project": r.get("project") or "—",
                "raw_hours": raw_h,
                "hours": billed_h,
                "amount": billed_h * rate,
            }
        )
    return rows


def _parse_date(s):
    try:
        return date.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def _prev_range(start, end):
    """The immediately-preceding range of equal length (for period-over-period)."""
    a, b = _parse_date(start), _parse_date(end)
    if not a or not b:
        return None, None
    length = (b - a).days + 1
    pe = a - timedelta(days=1)
    ps = pe - timedelta(days=length - 1)
    return ps.isoformat(), pe.isoformat()


def _count_workdays(start, end):
    """Weekdays (Mon–Fri) in [start, end] inclusive."""
    a, b = _parse_date(start), _parse_date(end)
    if not a or not b or b < a:
        return 0
    return sum(1 for i in range((b - a).days + 1) if (a + timedelta(days=i)).weekday() < 5)


def _pct_change(cur, prev):
    """Percent change cur vs prev, or None when there's no baseline."""
    if not prev:
        return None
    return (cur - prev) / prev * 100.0


def _last_of_month(d):
    first_next = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first_next - timedelta(days=1)


def _period_bounds(period, custom_start, custom_end, today):
    """(cur_start, cur_end, prev_start, prev_end) as ISO strings. Non-custom
    periods are to-date (end capped at `today`) and compared against the SAME
    elapsed span of the previous period — so Month is MTD vs the previous month's
    first-N days, never a partial month against a full one."""
    def iso(d):
        return d.isoformat()

    if period == "Custom":
        ps, pe = _prev_range(custom_start, custom_end)
        return custom_start, custom_end, ps, pe
    if period == "Day":
        y = today - timedelta(days=1)
        return iso(today), iso(today), iso(y), iso(y)
    if period == "Week":
        start = today - timedelta(days=today.weekday())
        return (iso(start), iso(today),
                iso(start - timedelta(days=7)), iso(today - timedelta(days=7)))
    if period == "Month":
        start = today.replace(day=1)
        prev_start = (start - timedelta(days=1)).replace(day=1)
        prev_end = prev_start.replace(day=min(today.day, _last_of_month(prev_start).day))
        return iso(start), iso(today), iso(prev_start), iso(prev_end)
    if period == "Year":
        start = today.replace(month=1, day=1)
        prev_start = start.replace(year=start.year - 1)
        try:
            prev_end = today.replace(year=today.year - 1)
        except ValueError:  # 29 Feb → 28 Feb in a non-leap previous year
            prev_end = today.replace(year=today.year - 1, day=28)
        return iso(start), iso(today), iso(prev_start), iso(prev_end)
    return None, None, None, None


def _cumulative_option(dates, values, target, accent=_ACCENT):
    """Cumulative hours over the period with a horizontal target reference line."""
    short = [d[5:] if isinstance(d, str) and len(d) >= 10 else str(d) for d in dates]
    cum, running = [], 0.0
    for v in values:
        running += v
        cum.append(round(running, 2))
    series = {
        "name": "Cumulative",
        "type": "line",
        "data": cum,
        "smooth": False,
        "symbol": "none",
        "lineStyle": {"width": 2, "color": accent},
        "itemStyle": {"color": accent},
        "areaStyle": {"color": _soft(accent)},
    }
    if target and target > 0:
        series["markLine"] = {
            "silent": True,
            "symbol": "none",
            "lineStyle": {"color": _AVG, "type": "dashed", "width": 2},
            "label": {
                "formatter": f"Target {target:.0f} h",
                "color": _AVG,
                "position": "insideEndTop",
            },
            "data": [{"yAxis": round(target, 1)}],
        }
    # Headroom above the higher of the cumulative peak / target so the target
    # line and its label are never clipped at the top edge.
    peak = max(cum[-1] if cum else 0.0, target if (target and target > 0) else 0.0)
    yaxis = {
        "type": "value",
        "axisLabel": {"color": _INK},
        "splitLine": {"lineStyle": {"color": _GRID}},
    }
    if peak > 0:
        yaxis["max"] = round(peak * 1.05, 1)
    return {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 8, "right": 60, "top": 12, "bottom": 4, "containLabel": True},
        "xAxis": {
            "type": "category",
            "data": short,
            "boundaryGap": False,
            "axisLabel": {"color": _INK},
            "axisLine": {"lineStyle": {"color": _GRID}},
        },
        "yAxis": yaxis,
        "series": [series],
    }


def _hbar_option(labels, values, colors=None, accent=_ACCENT):
    """Horizontal bar (magnitude) — biggest on top, rounded data-ends. Optional
    per-bar `colors` (e.g. a customer's own colour) override the `accent`."""
    # ECharts renders the first category at the bottom; reverse so the largest
    # value sits at the top.
    order = list(range(len(values)))[::-1]
    labels = [labels[i] for i in order]
    if colors:
        data = []
        for i in order:
            item = {"value": round(values[i], 2)}
            c = colors[i] if i < len(colors) else None
            if c:
                item["itemStyle"] = {"color": c, "borderRadius": [0, 4, 4, 0]}
            data.append(item)
    else:
        data = [round(values[i], 2) for i in order]
    return {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 4, "right": 28, "top": 8, "bottom": 4, "containLabel": True},
        "xAxis": {
            "type": "value",
            "axisLabel": {"color": _INK},
            "axisLine": {"show": False},
            "splitLine": {"lineStyle": {"color": _GRID}},
        },
        "yAxis": {
            "type": "category",
            "data": labels,
            # Truncate long project/customer names so they never overflow the card.
            "axisLabel": {"color": _INK, "width": 96, "overflow": "truncate"},
            "axisLine": {"show": False},
            "axisTick": {"show": False},
        },
        "series": [
            {
                "type": "bar",
                "data": data,
                "barMaxWidth": 18,
                "itemStyle": {"color": accent, "borderRadius": [0, 4, 4, 0]},
            }
        ],
    }


def _rolling_avg(values, window=7):
    """Trailing moving average (averages up to `window` preceding points incl.
    self), so it's defined even for short series."""
    out = []
    for i in range(len(values)):
        win = values[max(0, i - window + 1): i + 1]
        out.append(round(sum(win) / len(win), 2)) if win else out.append(0)
    return out


def _area_option(dates, values, accent=_ACCENT):
    """Daily hours over time: actual (area) + a rolling-average line."""
    short = [d[5:] if isinstance(d, str) and len(d) >= 10 else str(d) for d in dates]
    avg = _rolling_avg(values, 7)
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {
            "data": ["Daily", "Rolling avg"],
            "textStyle": {"color": _INK},
            "right": 8,
            "top": 0,
        },
        "grid": {"left": 8, "right": 14, "top": 30, "bottom": 4, "containLabel": True},
        "xAxis": {
            "type": "category",
            "data": short,
            "boundaryGap": False,
            "axisLabel": {"color": _INK},
            "axisLine": {"lineStyle": {"color": _GRID}},
        },
        "yAxis": {
            "type": "value",
            "axisLabel": {"color": _INK},
            "splitLine": {"lineStyle": {"color": _GRID}},
        },
        "series": [
            {
                "name": "Daily",
                "type": "line",
                "data": [round(v, 2) for v in values],
                "smooth": False,
                "symbol": "circle",
                "symbolSize": 5,
                "lineStyle": {"width": 2, "color": accent},
                "itemStyle": {"color": accent},
                "areaStyle": {"color": _soft(accent)},
            },
            {
                "name": "Rolling avg",
                "type": "line",
                "data": avg,
                "smooth": True,
                "symbol": "none",
                "lineStyle": {"width": 2, "color": _AVG, "type": "dashed"},
                "itemStyle": {"color": _AVG},
            },
        ],
    }


async def reports_page():
    """Visual time-analytics dashboard: filter → stat tiles + charts, CSV export."""
    core = await AppCore.get_or_initialize()
    QE = core.query_engine
    muted = UI_STYLES.get_layout_classes("muted_text")

    cust_df = await QE.query_db(
        "SELECT DISTINCT customer_name FROM customers WHERE is_current = 1 "
        "ORDER BY customer_name"
    )
    names = cust_df["customer_name"].dropna().tolist() if not cust_df.empty else []

    tset = core.ui_config.get("time_settings", {})
    default_round = int(tset.get("rounding_minutes", 0) or 0)
    mode = tset.get("rounding_mode", "nearest")
    currency = tset.get("currency", "")
    hours_per_day = float(tset.get("target_hours_per_day", 8) or 8)
    default_target = float(tset.get("target_percent", 100) or 100)

    # git_id → work-item title, for the "Top work items" chart.
    id2name = {}
    _dfd = core.devops_engine.df if core.devops_engine is not None else None
    if _dfd is not None and not _dfd.empty and "display_name" in _dfd.columns:
        for _, r in _dfd[["id", "display_name"]].dropna().iterrows():
            id2name[int(r["id"])] = str(r["display_name"])

    # Per-customer settings: expected work %, billing rounding override, colour.
    meta_df = await QE.query_db(
        "SELECT customer_name, expected_work_pct, billing_round_minutes, color "
        "FROM customers WHERE is_current = 1"
    )
    cust_meta = {}
    if not meta_df.empty:
        for _, r in meta_df.iterrows():
            cust_meta[r["customer_name"]] = {
                "expected": (float(r["expected_work_pct"])
                             if pd.notna(r["expected_work_pct"]) else None),
                "round": (int(r["billing_round_minutes"])
                          if pd.notna(r["billing_round_minutes"]) else 0),
                "color": (r["color"] or None),
            }

    def _effective_target_pct(sel):
        # Sum of the selected customers' expected % (empty selection = all
        # customers); falls back to the global default when nothing is set.
        targets = sel if sel else list(cust_meta.keys())
        vals = [cust_meta.get(c, {}).get("expected") for c in targets]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else default_target

    def _customer_round(sel):
        # A single selected customer contributes its own rounding default;
        # any other selection (none / several) uses the global default.
        if len(sel) == 1:
            return cust_meta.get(sel[0], {}).get("round") or default_round
        return default_round

    def _sel_label():
        return ", ".join(state["customers"]) if state["customers"] else "All"

    def _cust_display():
        # Compact one-line summary for the multi-select field (chips would grow
        # the toolbar unboundedly): names when few, a count when many.
        sel = state["customers"]
        if not sel:
            return "All customers"
        if len(sel) <= 2:
            return ", ".join(sel).replace('"', "'")
        return f"{len(sel)} customers selected"

    _saved = app.storage.user.get("report_customers")
    _init_custs = [c for c in _saved if c in names] if isinstance(_saved, list) else []
    _month = helpers.get_range_for("Month")
    state = {
        "customers": _init_custs,
        "period": "Month",
        "round": _customer_round(_init_custs),
        "custom_start": _month.split(" - ")[0],
        "custom_end": _month.split(" - ")[1],
        "range": ("", ""),
        "tiles": {"hours": 0.0, "amount": 0.0, "entries": 0, "days": 0},
        "deltas": {"hours": None, "amount": None, "entries": None},
        "target": {"hours": 0.0, "pct": 0.0},
        "by_project": ([], []),
        "by_project_colors": [],
        "by_customer": ([], []),
        "by_customer_colors": [],
        "over_time": ([], []),
        "top_items": ([], []),
        "top_items_colors": [],
    }

    async def _load():
        start, end, ps, pe = _period_bounds(
            state["period"], state["custom_start"], state["custom_end"], date.today()
        )
        state["range"] = (start, end)
        sel = [c for c in state["customers"] if c in names]
        specific = len(sel) > 0
        # No end_time filter — running timers (end_time NULL) are counted via _DUR.
        where = "date(start_time) BETWEEN ? AND ?"
        base = [start, end]
        cust_sql = where + (
            f" AND customer_name IN ({','.join('?' * len(sel))})" if specific else ""
        )
        cust_params = tuple(base + (sel if specific else []))

        if not (start and end):
            state["tiles"] = {"hours": 0.0, "amount": 0.0, "entries": 0, "days": 0}
            state["deltas"] = {"hours": None, "amount": None, "entries": None}
            state["target"] = {"hours": 0.0, "pct": 0.0}
            state["by_project"] = state["by_customer"] = state["over_time"] = ([], [])
            state["by_project_colors"] = []
            state["by_customer_colors"] = []
            state["top_items"] = ([], [])
            state["top_items_colors"] = []
            render_dashboard.refresh()
            return

        tot = await QE.query_db(
            f"""SELECT COALESCE(SUM({_DUR}), 0) AS h,
                       COALESCE(SUM(cost), 0) AS c,
                       COALESCE(SUM(total_time), 0) AS cth,
                       COUNT(*) AS n,
                       COUNT(DISTINCT date(start_time)) AS d
                FROM time WHERE {cust_sql}""",
            params=cust_params,
        )
        raw_h = float(tot.iloc[0]["h"]) if not tot.empty else 0.0
        raw_c = float(tot.iloc[0]["c"]) if not tot.empty else 0.0
        completed_h = float(tot.iloc[0]["cth"]) if not tot.empty else 0.0
        # Blended billable rate from completed entries (running timers have no
        # cost yet); applied to the live hours for an estimated amount.
        rate = (raw_c / completed_h) if completed_h else 0.0
        billed_h = round_hours(raw_h, state["round"], mode)
        state["tiles"] = {
            "hours": billed_h,
            "amount": billed_h * rate,
            "entries": int(tot.iloc[0]["n"]) if not tot.empty else 0,
            "days": int(tot.iloc[0]["d"]) if not tot.empty else 0,
        }

        # Period-over-period deltas — actual activity vs the SAME elapsed span of
        # the previous period (e.g. MTD vs the previous month's first N days).
        prev = await QE.query_db(
            f"""SELECT COALESCE(SUM({_DUR}),0) AS h, COALESCE(SUM(cost),0) AS c,
                       COUNT(*) AS n
                FROM time WHERE {cust_sql}""",
            params=tuple([ps, pe] + (sel if specific else [])),
        )
        p_h = float(prev.iloc[0]["h"]) if not prev.empty else 0.0
        p_c = float(prev.iloc[0]["c"]) if not prev.empty else 0.0
        p_n = int(prev.iloc[0]["n"]) if not prev.empty else 0
        state["deltas"] = {
            "hours": _pct_change(raw_h, p_h),
            "amount": _pct_change(raw_c, p_c),
            "entries": _pct_change(state["tiles"]["entries"], p_n),
        }

        # Utilisation target: 100% = hours_per_day × workdays; the % comes from
        # the customer's expected work % (summed across customers for "All").
        eff_target_pct = _effective_target_pct(sel)
        target_h = hours_per_day * _count_workdays(start, end) * (eff_target_pct / 100.0)
        state["target"] = {
            "hours": target_h,
            "pct": (raw_h / target_h * 100.0) if target_h else 0.0,
        }

        proj = await QE.query_db(
            f"""SELECT project_name AS k, customer_name AS cust, SUM({_DUR}) AS h
                FROM time WHERE {cust_sql}
                GROUP BY project_name, customer_name HAVING SUM({_DUR}) > 0
                ORDER BY h DESC LIMIT 12""",
            params=cust_params,
        )
        if not proj.empty:
            state["by_project"] = (
                proj["k"].fillna("—").tolist(), proj["h"].astype(float).tolist()
            )
            state["by_project_colors"] = [
                cust_meta.get(c, {}).get("color") for c in proj["cust"].tolist()
            ]
        else:
            state["by_project"] = ([], [])
            state["by_project_colors"] = []

        # Customer breakdown across the current selection (all when none chosen).
        byc = await QE.query_db(
            f"""SELECT customer_name AS k, SUM({_DUR}) AS h
                FROM time WHERE {cust_sql}
                GROUP BY customer_name HAVING SUM({_DUR}) > 0
                ORDER BY h DESC LIMIT 12""",
            params=cust_params,
        )
        state["by_customer"] = (
            (byc["k"].fillna("—").tolist(), byc["h"].astype(float).tolist())
            if not byc.empty else ([], [])
        )
        state["by_customer_colors"] = [
            cust_meta.get(n, {}).get("color") for n in state["by_customer"][0]
        ]

        ot = await QE.query_db(
            f"""SELECT date(start_time) AS d, SUM({_DUR}) AS h
                FROM time WHERE {cust_sql}
                GROUP BY date(start_time) ORDER BY d""",
            params=cust_params,
        )
        state["over_time"] = (
            (ot["d"].tolist(), ot["h"].astype(float).tolist())
            if not ot.empty else ([], [])
        )

        items = await QE.query_db(
            f"""SELECT git_id AS gid, customer_name AS cust, SUM({_DUR}) AS h
                FROM time WHERE {cust_sql} AND git_id IS NOT NULL AND git_id > 0
                GROUP BY git_id, customer_name HAVING SUM({_DUR}) > 0
                ORDER BY h DESC LIMIT 10""",
            params=cust_params,
        )
        if not items.empty:
            labels = [id2name.get(int(g), f"#{int(g)}") for g in items["gid"]]
            state["top_items"] = (labels, items["h"].astype(float).tolist())
            state["top_items_colors"] = [
                cust_meta.get(c, {}).get("color") for c in items["cust"].tolist()
            ]
        else:
            state["top_items"] = ([], [])
            state["top_items_colors"] = []

        render_dashboard.refresh()

    def _stat_tile(label, value, unit="", delta=None):
        with ui.card().props("flat").classes("rounded-md p-3 flex-1 min-w-36").style(_CARD):
            with ui.row().classes("items-baseline gap-1"):
                ui.label(value).classes("text-2xl font-bold text-white")
                if unit:
                    ui.label(unit).classes("text-sm " + muted)
            with ui.row().classes("items-center gap-2"):
                ui.label(label).classes("text-xs " + muted)
                if delta is not None:
                    arrow = "▲" if delta >= 0 else "▼"
                    ui.label(f"{arrow} {abs(delta):.0f}% vs prev").classes(
                        "text-xs " + muted
                    )

    def _chart_card(title, option, empty, full=False):
        width = "w-full" if full else "flex-1 min-w-80"
        with ui.card().props("flat").classes(f"rounded-md p-3 {width}").style(_CARD):
            ui.label(title).classes("text-sm font-semibold text-white mb-1")
            has_data = bool(option["series"][0]["data"])
            if has_data:
                ui.echart(option).classes("w-full").style("height: 300px;")
            else:
                with ui.column().classes("items-center justify-center w-full").style(
                    "height: 300px;"
                ):
                    ui.label(empty).classes("text-sm " + muted)

    @ui.refreshable
    def render_dashboard():
        t = state["tiles"]
        d = state["deltas"]
        tg = state["target"]
        cur = f" {currency}" if currency else ""
        pc, pv = state["by_project"]
        cc, cv = state["by_customer"]
        dts, dvs = state["over_time"]
        ic, iv = state["top_items"]

        # When exactly one customer is selected, use their own colour as the accent
        # across all of *their* charts; any other selection keeps the neutral accent.
        sel = state["customers"]
        acc = (cust_meta.get(sel[0], {}).get("color") or _ACCENT) if len(sel) == 1 else _ACCENT

        with ui.column().classes("w-full gap-3"):
            with ui.row().classes("w-full gap-3 flex-wrap"):
                _stat_tile("Total hours", f"{t['hours']:,.1f}", "h", d["hours"])
                _stat_tile("Amount", f"{t['amount']:,.0f}{cur}", "", d["amount"])
                _stat_tile("Entries", f"{t['entries']:,}", "", d["entries"])
                _stat_tile("Active days", f"{t['days']:,}")
                _stat_tile(f"of target ({tg['hours']:.0f} h)", f"{tg['pct']:.0f}%")

            _chart_card(
                "Hours over time", _area_option(dts, dvs, accent=acc),
                "No time in this range.", full=True,
            )
            _chart_card(
                "Cumulative vs target",
                _cumulative_option(dts, dvs, tg["hours"], accent=acc),
                "No time in this range.", full=True,
            )
            with ui.row().classes("w-full gap-3 flex-wrap"):
                _chart_card(
                    "Hours by project",
                    _hbar_option(pc, pv, colors=state["by_project_colors"], accent=acc),
                    "No projects.",
                )
                _chart_card(
                    "Hours by customer (all)",
                    _hbar_option(cc, cv, colors=state["by_customer_colors"]),
                    "No data.",
                )
            _chart_card(
                "Top work items",
                _hbar_option(ic, iv, colors=state["top_items_colors"], accent=acc),
                "No linked work items.", full=True,
            )

    async def _on_customer(e):
        sel = [c for c in (e.value or []) if c in names]
        state["customers"] = sel
        app.storage.user["report_customers"] = sel
        # A single selection adopts that customer's billing-rounding default
        # (applied to the billable tiles; there is no manual override control).
        state["round"] = _customer_round(sel)
        cust_select.props(f'display-value="{_cust_display()}"')
        cust_select.update()
        await _load()

    async def _on_period(value):
        state["period"] = value
        render_period_controls.refresh()
        await _load()

    @ui.refreshable
    def render_period_controls():
        segmented_chips(
            core.theme, [(p, p) for p in _PERIODS], state["period"],
            lambda v: _on_period(v),
        )
        if state["period"] == "Custom":
            async def _cs(e):
                state["custom_start"] = e.value
                await _load()

            async def _ce(e):
                state["custom_end"] = e.value
                await _load()

            ui.input("From", value=state["custom_start"], on_change=_cs).props(
                "type=date dense outlined"
            ).classes("w-36")
            ui.input("To", value=state["custom_end"], on_change=_ce).props(
                "type=date dense outlined"
            ).classes("w-36")

    def _export_csv():
        start, end = state["range"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([f"Report — {_sel_label()}", f"{start} to {end}"])
        w.writerow([])
        w.writerow(["Project", "Hours"])
        for k, v in zip(*state["by_project"]):
            w.writerow([k, f"{v:.2f}"])
        w.writerow([])
        w.writerow(["Billable hours", f"{state['tiles']['hours']:.2f}"])
        w.writerow(["Amount", f"{state['tiles']['amount']:.2f}"])
        _slug = "_".join(state["customers"]) if state["customers"] else "All"
        ui.download(buf.getvalue().encode("utf-8-sig"), f"report_{_slug}_{start}_{end}.csv")

    with toolbar(core.theme):
        with toolbar_group(core.theme, divider_after=True):
            ui.icon("insights", size="md").classes(f"text-{core.theme.get('accent')}")
            ui.label("Reports").classes(UI_STYLES.get_layout_classes("page_title"))

        with toolbar_group(core.theme, "Customers", divider_after=True):
            cust_select = ui.select(
                names, value=state["customers"], on_change=_on_customer,
                multiple=True, clearable=True,
            ).props(
                f'dense outlined display-value="{_cust_display()}"'
            ).classes("w-56 shrink-0").tooltip(
                "Pick one or more customers to show — leave empty for all. "
                "Your selection is remembered."
            )

        with toolbar_group(core.theme, "Period", divider_after=False):
            render_period_controls()

        ui.space()

        ui.button("CSV", icon="download", on_click=_export_csv).props(
            "flat dense no-caps color=white"
        ).tooltip("Export summary as CSV")

    with page_card():
        render_dashboard()

    await _load()
