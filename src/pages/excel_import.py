"""Settings → Data → "Import time from Excel" (hosted WorkTimer): a time report
copied from a spreadsheet and pasted in. Its columns are guessed and can be
corrected, its customers set up in one table (an hourly rate each, active or
not), and nothing is saved until Import. Earlier imports can be undone.
Reading the paste: src/paste_import.py; saving it: PgDatabase's pasted-time
methods.
"""

from datetime import timedelta

from nicegui import ui

from .. import clock, paste_import
from ..helpers import UI_STYLES

FIELD_LABELS = {"date": "Date", "customer": "Customer", "project": "Project", "hours": "Hours",
                "start": "Start", "end": "End", "comment": "Comment",
                paste_import.IGNORE: "— ignore —"}
PREVIEW_ROWS = 5
PROBLEMS_SHOWN = 15
ACTIVE_WITHIN = timedelta(days=90)  # a new customer with time this recent starts active
DOCS = "/info?tab=excel_import"  # docs/excel_import.md on the Documentation page


def _hours(value) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", " ")


def _day(date_key: int) -> str:
    text = str(int(date_key))
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def render_excel_import_card(core) -> None:
    db = core.query_engine.db
    if getattr(db, "backend", "sqlite") != "postgres":
        return
    muted = UI_STYLES.get_layout_classes("muted_text")
    accent = core.theme.get("accent")
    state: dict = {"rows": [], "has_header": False, "fields": [], "entries": [],
                   "rates": {}, "active": {}}

    with ui.card().props("flat bordered").classes("w-full rounded-lg p-4"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Import time from Excel").classes(
                f"text-sm font-semibold text-{accent} flex-1")
            # In a new browser tab: a table pasted here stays.
            ui.button("How it works", icon="open_in_new",
                      on_click=lambda: ui.navigate.to(DOCS, new_tab=True)).props(
                "flat dense no-caps size=sm")
        ui.label(
            "In Excel, select your time report — its header row included — copy it (Ctrl+C) "
            "and paste it here (Ctrl+V). One row per entry, with at least a date, a customer "
            "and hours (or a start and end time). Customers and projects not here yet are "
            "created. Nothing is saved until you press Import."
        ).classes("text-xs " + muted)
        paste = ui.textarea(placeholder="Paste your time report here").props(
            "outlined dense debounce=400").classes("w-full font-mono text-xs").style(
            "max-height: 9rem")
        columns_box = ui.column().classes("w-full gap-2")
        result_box = ui.column().classes("w-full gap-2")
        imports_box = ui.column().classes("w-full gap-1 mt-2")

    def render_columns():
        columns_box.clear()
        rows, fields = state["rows"], state["fields"]
        if not rows:
            return
        with columns_box:
            ui.checkbox("The first row is a header", value=state["has_header"],
                        on_change=lambda e: on_header(e.value)).props("dense")
            with ui.element("div").classes("w-full overflow-x-auto"):
                with ui.grid(columns=len(fields)).classes("gap-x-3 gap-y-0 text-xs").style(
                        "grid-template-columns: repeat(%d, minmax(7rem, auto))" % len(fields)):
                    for i, field in enumerate(fields):
                        ui.select(FIELD_LABELS, value=field,
                                  on_change=lambda e, i=i: on_field(i, e.value)).props(
                            "dense outlined options-dense").classes("text-xs")
                    shown = rows[:PREVIEW_ROWS + (1 if state["has_header"] else 0)]
                    for r, row in enumerate(shown):
                        header = state["has_header"] and r == 0
                        for cell in row:
                            ui.label(cell).classes(
                                "truncate leading-5 " + ("font-semibold" if header else "")).style(
                                "max-width: 14rem")
            body = len(rows) - (1 if state["has_header"] else 0)
            if body > PREVIEW_ROWS:
                ui.label(f"… and {body - PREVIEW_ROWS} more rows").classes("text-xs " + muted)

    async def on_header(value: bool):
        state["has_header"] = value
        render_columns()
        await evaluate()

    async def on_field(i: int, value: str):
        fields = state["fields"]
        for j, other in enumerate(fields):  # one column per field
            if j != i and other == value and value != paste_import.IGNORE:
                fields[j] = paste_import.IGNORE
        fields[i] = value
        render_columns()
        await evaluate()

    async def on_paste():
        result_box.clear()
        try:
            state["rows"] = paste_import.read_table(paste.value or "")
        except ValueError as e:
            state["rows"] = []
            render_columns()
            with result_box:
                ui.label(str(e)).classes("text-xs text-negative")
            return
        state["has_header"], state["fields"] = paste_import.guess_columns(state["rows"])
        render_columns()
        await evaluate()

    async def evaluate():
        result_box.clear()
        state["entries"] = []
        if not state["rows"]:
            return
        entries, problems, skipped = paste_import.parse(
            state["rows"], state["has_header"], state["fields"])
        with result_box:
            if problems:
                ui.label(f"{len(problems)} row{'s' if len(problems) != 1 else ''} to fix in "
                         "Excel before importing — then copy and paste again:").classes(
                    "text-xs text-negative font-semibold")
                for p in problems[:PROBLEMS_SHOWN]:
                    ui.label(f"Row {p.row}: {p.message}" if p.row else p.message).classes(
                        "text-xs text-negative")
                if len(problems) > PROBLEMS_SHOWN:
                    ui.label(f"… and {len(problems) - PROBLEMS_SHOWN} more").classes(
                        "text-xs text-negative")
        if not entries:
            return
        try:
            check = await core.query_engine.function_db("check_pasted_entries", entries)
        except Exception as e:
            with result_box:
                ui.label(f"Couldn't check the entries: {e}").classes("text-xs text-negative")
            return
        state["entries"] = entries
        render_customers(entries, check, skipped, blocked=bool(problems))

    def render_customers(entries, check, skipped: int, blocked: bool):
        groups = paste_import.by_customer(entries)
        state["rates"], state["active"] = {}, {}
        recent = clock.today_local() - ACTIVE_WITHIN
        heads = ["Customer", "Entries", "Hours", "Period", "Projects", "Already here",
                 "Hourly rate", "Active"]
        already = sum(info["already_here"] for info in check.values())
        new = len(entries) - already
        with result_box:
            ui.label("Customers").classes("text-xs font-semibold mt-1")
            with ui.element("div").classes("w-full overflow-x-auto"):
                with ui.grid(columns=len(heads)).classes(
                        "gap-x-4 gap-y-1 items-center text-xs").style(
                        "grid-template-columns: repeat(8, auto)"):
                    for head in heads:
                        ui.label(head).classes(muted)
                    for g in groups:
                        info = check[g["customer"]]
                        status = ("new" if not info["exists"] else
                                  "here" if info["enabled"] else "here, disabled")
                        with ui.row().classes("gap-1 items-center no-wrap"):
                            ui.label(info["name"]).classes("font-semibold")
                            ui.badge(status).props(
                                f"{'color=' + accent if status == 'new' else 'color=grey-7'} "
                                "outline")
                        ui.label(str(g["entries"])).classes("text-right tabular-nums")
                        ui.label(_hours(g["hours"])).classes("text-right tabular-nums")
                        ui.label(f"{g['first']} – {g['last']}").classes("tabular-nums")
                        ui.label(", ".join(f"{p} (new)" if p in info["new_projects"] else p
                                           for p in g["projects"]))
                        ui.label(str(info["already_here"] or "")).classes(
                            "text-right tabular-nums")
                        if info["exists"]:
                            ui.label("")
                            ui.label("")
                        else:
                            state["rates"][g["customer"]] = ui.number(
                                min=0, step=1, placeholder="0").props(
                                "dense outlined suffix=SEK").style("width: 8rem")
                            state["active"][g["customer"]] = ui.checkbox(
                                value=g["last"] >= recent).props("dense")
            note = (f"{new} entr{'y' if new == 1 else 'ies'} to import"
                    + (f" · {already} already here (skipped)" if already else "")
                    + (f" · {skipped} row{'s' if skipped != 1 else ''} without time (skipped)"
                       if skipped else ""))
            ui.label(note).classes("text-xs " + muted)
            if state["rates"]:
                ui.label("A new customer's rate applies from its first imported day; left "
                         "empty, it is 0 — set it later under Customers → Update. Customers "
                         "not ticked Active are created disabled: their time still counts in "
                         "Reports.").classes("text-xs " + muted)
            with ui.row().classes("w-full justify-end"):
                button = ui.button(f"Import {new} entr{'y' if new == 1 else 'ies'}",
                                   icon="upload", on_click=do_import).props(
                    "color=primary no-caps")
                if blocked or not new:
                    button.props("disable")

    async def do_import(e):
        e.sender.props("loading")
        rates = {name: w.value for name, w in state["rates"].items() if w.value}
        inactive = {name for name, box in state["active"].items() if not box.value}
        try:
            result = await core.query_engine.function_db(
                "import_pasted_entries", state["entries"], rates=rates, inactive=inactive)
        except Exception as ex:
            core.logger.error(f"Excel import failed: {ex}")
            ui.notify(f"Import failed: {ex}", type="negative", multi_line=True)
            e.sender.props(remove="loading")
            return
        parts = [f"Imported {result['entries']} time entries"]
        if result["skipped"]:
            parts.append(f"{result['skipped']} already here were skipped")
        if result["customers"]:
            parts.append(f"new customers: {', '.join(result['customers'])}")
        ui.notify("; ".join(parts), type="positive", multi_line=True)
        paste.value = ""
        state.update(rows=[], fields=[], entries=[])
        columns_box.clear()
        result_box.clear()
        core.event_bus.emit("ui_refresh_requested")
        await refresh_imports()

    async def refresh_imports():
        imports_box.clear()
        try:
            df = await core.query_engine.function_db("get_imports")
        except Exception as e:
            core.logger.error(f"Listing the Excel imports failed: {e}")
            return
        if df.empty:
            return
        with imports_box:
            ui.label("Earlier imports").classes("text-xs font-semibold")
            for row in df.itertuples():
                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                    when = row.imported_at.to_pydatetime().astimezone().strftime("%Y-%m-%d %H:%M")
                    entries = int(row.entries)
                    ui.label(f"{when} · {entries} entr{'y' if entries == 1 else 'ies'} · "
                             f"{_day(row.first_day)} – {_day(row.last_day)}").classes(
                        "text-xs tabular-nums " + ("" if entries else muted))
                    if entries:
                        ui.button("Undo", icon="undo",
                                  on_click=lambda _, r=row, w=when: undo(r.import_batch, w,
                                                                         int(r.entries))).props(
                            "flat dense no-caps size=sm")
                    else:
                        ui.label("undone").classes("text-xs " + muted)

    async def undo(batch: str, when: str, entries: int):
        with ui.dialog() as dialog, ui.card().classes("p-4 gap-3").style("max-width: 30rem"):
            ui.label(f"Undo the import of {when}?").classes("text-base font-semibold")
            ui.label(f"Its {entries} time entries are removed. Customers and projects it "
                     "created stay — disable them if you don't need them.").classes("text-sm")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button("Undo import", on_click=lambda: dialog.submit(True)).props(
                    "color=negative no-caps")
        confirmed = await dialog
        dialog.delete()
        if not confirmed:
            return
        try:
            removed = await core.query_engine.function_db("undo_import", batch)
        except Exception as ex:
            ui.notify(f"Undo failed: {ex}", type="negative")
            return
        ui.notify(f"Import undone: {removed} time entries removed", type="positive")
        core.event_bus.emit("ui_refresh_requested")
        await refresh_imports()

    paste.on_value_change(on_paste)
    ui.timer(0, refresh_imports, once=True)
