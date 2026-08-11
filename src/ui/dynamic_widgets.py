"""
Dynamic UI Widgets

Self-refreshing widgets that know how to update their own data.
Base class handles parent-child relationships, data fetching, and common operations.
"""

from abc import ABC, abstractmethod
import asyncio
import json
import logging
import re
from nicegui import ui
from typing import Callable, Optional, Any, Dict
from datetime import date


logger = logging.getLogger(__name__)


_MD_ALIGN_SEP = {"center": ":--:", "right": "---:"}


def build_markdown_table(headers, rows, aligns=None):
    """Build a GitHub-flavored markdown table.

    headers: list of column header strings.
    rows: list of rows, each a list of cell values (ragged rows are padded,
        extra cells are dropped to match the header count).
    aligns: optional per-column alignment ('left' | 'center' | 'right');
        anything else (or missing) is treated as left.
    Returns "" when there are no columns. Pipes and newlines inside cells are
    escaped/flattened so they can't break the table.
    """
    ncols = len(headers)
    if ncols == 0:
        return ""

    def _cell(value):
        text = "" if value is None else str(value)
        return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()

    aligns = [
        (aligns[i] if aligns and i < len(aligns) else "left") for i in range(ncols)
    ]
    lines = [
        "| " + " | ".join(_cell(h) for h in headers) + " |",
        "| " + " | ".join(_MD_ALIGN_SEP.get(a, ":---") for a in aligns) + " |",
    ]
    for row in rows:
        cells = [_cell(row[i]) if i < len(row) else "" for i in range(ncols)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


_MD_SEP_CELL_RE = re.compile(r"^:?-+:?$")


def _split_md_row(line):
    """Split a `| a | b |` markdown row into trimmed cells (handles \\| escapes)."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", line)]


def parse_markdown_table(text):
    """Parse a GFM markdown table into (headers, rows, aligns), or None when the
    text isn't a recognizable table (a header row followed by a `---` separator
    row). Rows are padded/truncated to the header column count."""
    lines = [ln for ln in (raw.strip() for raw in str(text).splitlines()) if ln]
    if len(lines) < 2:
        return None
    sep_cells = _split_md_row(lines[1])
    if not sep_cells or not all(_MD_SEP_CELL_RE.match(c) for c in sep_cells):
        return None

    headers = _split_md_row(lines[0])
    ncols = len(headers)

    def _align(cell):
        left, right = cell.startswith(":"), cell.endswith(":")
        if left and right:
            return "center"
        if right:
            return "right"
        return "left"

    aligns = [_align(sep_cells[i]) if i < len(sep_cells) else "left" for i in range(ncols)]
    rows = []
    for ln in lines[2:]:
        cells = _split_md_row(ln)
        rows.append([cells[i] if i < len(cells) else "" for i in range(ncols)])
    return headers, rows, aligns


def _table_preview_html(headers, rows, aligns):
    """Render an HTML table with per-column text-align, so the dialog preview
    visibly reflects the chosen alignment (ui.markdown doesn't show it clearly)."""
    ncols = len(headers)
    aligns = [(aligns[i] if i < len(aligns) else "left") for i in range(ncols)]

    def _esc(value):
        return (
            str("" if value is None else value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    cell_css = "border:1px solid #64748b; padding:4px 10px;"
    head = "".join(
        f'<th style="text-align:{aligns[i]}; {cell_css} background:#334155; color:#e2e8f0;">'
        f"{_esc(headers[i])}</th>"
        for i in range(ncols)
    )
    rows_html = ""
    for row in rows:
        tds = "".join(
            f'<td style="text-align:{aligns[i]}; {cell_css}">'
            f'{_esc(row[i]) if i < len(row) else ""}</td>'
            for i in range(ncols)
        )
        rows_html += f"<tr>{tds}</tr>"
    return (
        '<table style="border-collapse:collapse; font-size:0.85rem;">'
        f"<thead><tr>{head}</tr></thead><tbody>{rows_html}</tbody></table>"
    )


# ── Reusable markdown editing helpers (used by the editor-with-preview widget
#    and the notepad, both of which wrap a ui.codemirror) ─────────────────────


def _cm_run(editor, body: str):
    """Run a JS snippet against `editor`'s CodeMirror view. `v` is the
    EditorView; a programmatic dispatch syncs back to the server value."""
    ui.run_javascript(
        f"const c = getElement({editor.id});"
        f"if (c && c.editor) {{ const v = c.editor; {body} v.focus(); }}"
    )


def md_wrap(editor, before: str, after: str):
    """Wrap the selection with markers; with no selection, place the cursor
    between them ready to type."""
    b, a = json.dumps(before), json.dumps(after)
    _cm_run(
        editor,
        f"""
        const r = v.state.selection.main;
        const sel = v.state.sliceDoc(r.from, r.to);
        const before = {b}, after = {a};
        v.dispatch({{
            changes: {{from: r.from, to: r.to, insert: before + sel + after}},
            selection: sel
                ? {{anchor: r.from + before.length, head: r.from + before.length + sel.length}}
                : {{anchor: r.from + before.length}},
        }});
        """,
    )


def md_prefix(editor, prefix: str):
    """Add `prefix` to the start of every selected line, or remove it if already
    present (toggle)."""
    p = json.dumps(prefix)
    _cm_run(
        editor,
        f"""
        const prefix = {p};
        const r = v.state.selection.main;
        const first = v.state.doc.lineAt(r.from).number;
        const last = v.state.doc.lineAt(r.to).number;
        const changes = [];
        for (let n = first; n <= last; n++) {{
            const line = v.state.doc.line(n);
            if (line.text.startsWith(prefix)) {{
                changes.push({{from: line.from, to: line.from + prefix.length, insert: ''}});
            }} else {{
                changes.push({{from: line.from, insert: prefix}});
            }}
        }}
        v.dispatch({{changes}});
        """,
    )


def md_numbered(editor):
    """Number every selected line (1., 2., …); toggle off if already numbered."""
    _cm_run(
        editor,
        """
        const r = v.state.selection.main;
        const first = v.state.doc.lineAt(r.from).number;
        const last = v.state.doc.lineAt(r.to).number;
        const re = /^\\d+\\.\\s/;
        const changes = [];
        let i = 1;
        for (let n = first; n <= last; n++) {
            const line = v.state.doc.line(n);
            const m = line.text.match(re);
            if (m) {
                changes.push({from: line.from, to: line.from + m[0].length, insert: ''});
            } else {
                changes.push({from: line.from, insert: (i++) + '. '});
            }
        }
        v.dispatch({changes});
        """,
    )


def md_link(editor):
    """Insert [text](url) around the selection, selecting `url` to type."""
    _cm_run(
        editor,
        """
        const r = v.state.selection.main;
        const sel = v.state.sliceDoc(r.from, r.to);
        const text = sel || 'text';
        const insert = '[' + text + '](url)';
        const urlStart = r.from + text.length + 3;
        v.dispatch({
            changes: {from: r.from, to: r.to, insert: insert},
            selection: {anchor: urlStart, head: urlStart + 3},
        });
        """,
    )


def md_insert(editor, text):
    """Insert `text` at the editor's cursor (replacing any selection)."""
    _cm_run(editor, f"v.dispatch(v.state.replaceSelection({json.dumps(text)}));")


def _render_image_button(editor, uploader):
    """A toolbar image button that opens the file picker directly (no dialog).
    A hidden ui.upload does the transfer; the button clicks its file input
    client-side, which preserves the user gesture the picker requires."""

    async def _on_upload(e):
        try:
            content = e.content.read()
            url = await uploader(e.name, content)
        except Exception as ex:
            logger.exception(f"Image upload failed: {ex}")
            url = None
        if url:
            md_insert(editor, f"![{e.name}]({url})\n")
            ui.notify("Image inserted", type="positive")
        else:
            ui.notify("Image upload failed", type="negative")

    up = (
        ui.upload(on_upload=_on_upload, auto_upload=True)
        .props('accept="image/*"')
        .classes("hidden")
    )
    btn = ui.button(icon="image").props("flat dense size=sm")
    btn.tooltip("Insert image")
    btn.on(
        "click",
        js_handler=f'() => getHtmlElement({up.id}).querySelector("input").click()',
    )


def render_markdown_toolbar(editor, image_uploader=None):
    """A row of markdown formatting buttons operating on `editor` (a
    ui.codemirror). Each transforms the current selection (wrap for inline marks,
    prefix lines for block marks) so the syntax is discoverable. Reused by the
    editor-with-preview widget and the notepad. When `image_uploader` is given
    (an async `(name, bytes) -> url` callable), an Insert-image button appears."""

    def _btn(icon: str, tip: str, handler):
        ui.button(icon=icon, on_click=handler).props("flat dense size=sm").tooltip(tip)

    def _sep():
        ui.element("div").classes("h-5 w-px bg-gray-500 mx-1 opacity-50")

    with ui.row().classes("w-full items-center gap-1 mb-1 flex-wrap") as toolbar_row:
        _btn("format_bold", "Bold", lambda: md_wrap(editor, "**", "**"))
        _btn("format_italic", "Italic", lambda: md_wrap(editor, "*", "*"))
        _btn("code", "Inline code", lambda: md_wrap(editor, "`", "`"))
        _sep()
        _btn("format_list_bulleted", "Bullet list", lambda: md_prefix(editor, "- "))
        _btn("format_list_numbered", "Numbered list", lambda: md_numbered(editor))
        _btn("checklist", "Task checkbox", lambda: md_prefix(editor, "- [ ] "))
        _sep()
        _btn("title", "Heading", lambda: md_prefix(editor, "## "))
        _btn("format_quote", "Quote", lambda: md_prefix(editor, "> "))
        _btn("data_object", "Code block", lambda: md_wrap(editor, "```\n", "\n```"))
        _sep()
        _btn("link", "Link", lambda: md_link(editor))
        if image_uploader is not None:
            _render_image_button(editor, image_uploader)
        ui.button(
            "Table", icon="table_chart", on_click=lambda: open_markdown_table_dialog(editor)
        ).props("flat dense no-caps size=sm").tooltip("Insert a markdown table")

    return toolbar_row


def inject_image_paste(editor, endpoint, extra_fields=None):
    """Attach a paste handler to `editor`'s CodeMirror that uploads pasted images
    to `endpoint` (POST, multipart) with `extra_fields` and inserts them at the
    cursor. Retries briefly until the CodeMirror view is mounted."""
    fields_js = "".join(
        f"fd.append({json.dumps(k)}, {json.dumps(v)});" for k, v in (extra_fields or {}).items()
    )
    ui.run_javascript(
        f"""
        let _tries = 0;
        (function attach() {{
            const c = getElement({editor.id});
            if (!c || !c.editor) {{ if (_tries++ < 25) setTimeout(attach, 200); return; }}
            const view = c.editor;
            const dom = view.dom;
            if (dom._imagePasteEnabled) return;
            dom._imagePasteEnabled = true;
            dom.addEventListener('paste', async (event) => {{
                const items = event.clipboardData && event.clipboardData.items;
                if (!items) return;
                for (const item of items) {{
                    if (!item.type.startsWith('image/')) continue;
                    event.preventDefault();
                    const blob = item.getAsFile();
                    const fd = new FormData();
                    fd.append('file', blob, 'paste.png');
                    {fields_js}
                    try {{
                        const resp = await fetch({json.dumps(endpoint)}, {{method: 'POST', body: fd}});
                        if (!resp.ok) return;
                        const data = await resp.json();
                        if (!data.path) return;
                        view.dispatch(view.state.replaceSelection('![image](' + data.path + ')\\n'));
                        view.focus();
                    }} catch (err) {{ console.error('Image paste upload failed', err); }}
                }}
            }});
        }})();
        """
    )


def open_markdown_table_dialog(editor):
    """Grid-based markdown-table builder. Fills cells in a small grid (with
    optional per-column alignment), previews the result live, and appends the
    generated table to the editor."""
    from .. import helpers

    state = {"ncols": 3, "nrows": 2}
    headers: dict = {}
    aligns: dict = {}
    body: dict = {}
    dim_inputs: dict = {}

    def _headers_list():
        return [headers.get(c, "") for c in range(state["ncols"])]

    def _aligns_list():
        return [aligns.get(c, "left") for c in range(state["ncols"])]

    def _rows_list():
        return [
            [body.get((r, c), "") for c in range(state["ncols"])]
            for r in range(state["nrows"])
        ]

    def _markdown() -> str:
        return build_markdown_table(_headers_list(), _rows_list(), _aligns_list())

    with ui.dialog() as dlg, ui.card().style(
        "min-width: 620px; max-width: 92vw;"
    ):
        ui.label("Insert table").classes("text-lg font-semibold")

        def _set_dim(key: str, value, lo: int, hi: int):
            try:
                state[key] = max(lo, min(int(value), hi))
            except (TypeError, ValueError):
                return
            grid.refresh()
            preview.refresh()

        # Paste an existing table to edit it.
        with ui.expansion("Paste a table to edit", icon="content_paste").classes(
            "w-full"
        ):
            paste_box = (
                ui.textarea(placeholder="Paste a markdown table here…")
                .props("outlined autogrow")
                .classes("w-full")
            )

            def _load():
                parsed = parse_markdown_table(paste_box.value or "")
                if not parsed:
                    ui.notify(
                        "Couldn't recognize a markdown table", type="warning"
                    )
                    return
                h, rows, algn = parsed
                headers.clear()
                aligns.clear()
                body.clear()
                state["ncols"] = max(1, min(len(h), 8))
                state["nrows"] = max(1, min(len(rows), 30)) if rows else 1
                for c in range(state["ncols"]):
                    headers[c] = h[c] if c < len(h) else ""
                    aligns[c] = algn[c] if c < len(algn) else "left"
                for r in range(state["nrows"]):
                    for c in range(state["ncols"]):
                        body[(r, c)] = (
                            rows[r][c]
                            if r < len(rows) and c < len(rows[r])
                            else ""
                        )
                if "cols" in dim_inputs:
                    dim_inputs["cols"].value = state["ncols"]
                if "rows" in dim_inputs:
                    dim_inputs["rows"].value = state["nrows"]
                grid.refresh()
                preview.refresh()

            ui.button("Load into grid", icon="download", on_click=_load).props(
                "flat dense no-caps"
            )

        with ui.row().classes("items-center gap-4"):
            dim_inputs["cols"] = (
                ui.number(
                    "Columns", value=state["ncols"], min=1, max=8, step=1,
                    on_change=lambda e: _set_dim("ncols", e.value, 1, 8),
                )
                .props("dense outlined")
                .style("width: 110px;")
            )
            dim_inputs["rows"] = (
                ui.number(
                    "Rows", value=state["nrows"], min=1, max=30, step=1,
                    on_change=lambda e: _set_dim("nrows", e.value, 1, 30),
                )
                .props("dense outlined")
                .style("width: 110px;")
            )

        @ui.refreshable
        def grid():
            nc = state["ncols"]
            for c in range(nc):
                headers.setdefault(c, f"Column {c + 1}")
                aligns.setdefault(c, "left")
            col_css = f"grid-template-columns: repeat({nc}, 1fr); gap: 0.4rem;"
            with ui.element("div").classes("w-full").style(
                f"display: grid; {col_css}"
            ):
                # Header inputs
                for c in range(nc):
                    ui.input(value=headers.get(c, "")).props(
                        "dense outlined"
                    ).classes("w-full font-semibold").on_value_change(
                        lambda e, c=c: (headers.__setitem__(c, e.value), preview.refresh())
                    )
                # Per-column alignment
                for c in range(nc):
                    ui.toggle(
                        {"left": "L", "center": "C", "right": "R"},
                        value=aligns.get(c, "left"),
                    ).props("dense no-caps unelevated").on_value_change(
                        lambda e, c=c: (aligns.__setitem__(c, e.value), preview.refresh())
                    )
                # Body cells
                for r in range(state["nrows"]):
                    for c in range(nc):
                        ui.input(value=body.get((r, c), "")).props(
                            "dense outlined"
                        ).classes("w-full").on_value_change(
                            lambda e, r=r, c=c: (body.__setitem__((r, c), e.value), preview.refresh())
                        )

        grid()

        ui.label("Preview").classes(
            "text-sm mt-2 " + helpers.UI_STYLES.get_layout_classes("muted_text")
        )

        @ui.refreshable
        def preview():
            # HTML table (not ui.markdown) so per-column alignment is visible.
            ui.html(
                _table_preview_html(_headers_list(), _rows_list(), _aligns_list())
            )

        preview()

        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Cancel", on_click=dlg.close).props("flat")

            def _copy():
                ui.clipboard.write(_markdown())
                ui.notify(
                    "Table copied — paste it where you want (Ctrl/⌘+V)",
                    type="positive",
                )
                dlg.close()

            ui.button("Copy", icon="content_copy", on_click=_copy).props(
                "flat no-caps"
            )

            def _insert():
                # Insert at the editor's cursor via the CodeMirror view. A
                # programmatic dispatch fires the change listener, so the
                # server-side .value stays in sync. Ensures the table starts
                # on its own line.
                payload = json.dumps(_markdown())
                ui.run_javascript(
                    f"""
                    const c = getElement({editor.id});
                    if (c && c.editor) {{
                        const v = c.editor;
                        const pos = v.state.selection.main.from;
                        const before = pos > 0 ? v.state.doc.sliceString(pos - 1, pos) : '\\n';
                        const prefix = (pos === 0 || before === '\\n') ? '' : '\\n\\n';
                        v.dispatch(v.state.replaceSelection(prefix + {payload} + '\\n'));
                        v.focus();
                    }}
                    """
                )
                dlg.close()

            ui.button(
                "Insert at cursor", icon="check", on_click=_insert
            ).props("color=primary no-caps")

    dlg.open()


class DynamicWidget(ABC):
    """
    Abstract base class for all dynamic widgets.

    Handles:
    - Parent-child relationships and auto-wiring
    - Data fetching and refresh logic
    - Value proxying to underlying widget
    - Common widget operations
    """

    def __init__(
        self,
        name: str,
        data_fetcher: Optional[Callable] = None,
        options_source: str = "",
        parent: Optional["DynamicWidget"] = None,
        label: str = "",
        initial_value: Any = None,
        field_config: Dict = None,
        **widget_kwargs,
    ):
        """
        Initialize dynamic widget.

        Args:
            name: Field name
            data_fetcher: Async callable(options_source, parent_val) -> data for refresh
            options_source: Key in data_sources dict to fetch data from
            parent: Parent DynamicWidget (for dependent fields)
            label: Widget label
            initial_value: Initial value to set
            field_config: Full field configuration dict
            **widget_kwargs: Additional args passed to widget creation
        """
        self.name = name
        self.data_fetcher = data_fetcher
        self.options_source = options_source
        self.parent = parent
        self.label = label
        self.field_config = field_config or {}
        self.widget_kwargs = widget_kwargs

        # Create the actual UI widget (implemented by subclass)
        self.widget = self._create_widget()

        # Set initial value if provided
        if initial_value is not None:
            self.widget.value = initial_value
        elif "default" in self.field_config:
            self.widget.value = self.field_config["default"]

        # Auto-wire to parent if exists
        if self.parent:
            # Check if parent_update is enabled (for HTML/markdown previews)
            if self.field_config.get("parent_update", False):
                # Wire up on_change for live updates
                if hasattr(self.parent.widget, "on_change"):
                    self.parent.widget.on_change(lambda e: self._on_parent_change())
                elif hasattr(self.parent.widget, "on_value_change"):
                    self.parent.widget.on_value_change(
                        lambda e: self._on_parent_change()
                    )
            else:
                # Standard parent-child relationship (value changes)
                if hasattr(self.parent.widget, "on_value_change"):
                    self.parent.widget.on_value_change(
                        lambda e: self._on_parent_change()
                    )

    @abstractmethod
    def _create_widget(self):
        """Create and return the actual NiceGUI widget. Implemented by subclasses."""
        pass

    def _on_parent_change(self):
        """Called when parent value changes"""
        asyncio.create_task(self.refresh())

    async def refresh(self):
        """Refresh widget data based on current parent value (if any)"""
        if not self.data_fetcher:
            return

        if not self.options_source and not self.parent:
            return

        try:
            parent_val = self.parent.widget.value if self.parent else None
            await self._refresh_impl(parent_val)
        except Exception as e:
            logger.exception(f"Error refreshing widget '{self.name}': {e}")

    async def _refresh_impl(self, parent_val):
        """
        Implement refresh logic for this widget type.
        Override in subclasses if needed. Default does nothing.
        """
        pass

    @property
    def value(self):
        """Get current value"""
        return self.widget.value

    @value.setter
    def value(self, val):
        """Set current value"""
        self.widget.value = val

    def update(self):
        """Update the widget"""
        self.widget.update()

    def on_value_change(self, handler):
        """Register value change handler"""
        self.widget.on_value_change(handler)

    def classes(self, *args, **kwargs):
        """Apply CSS classes to widget"""
        return self.widget.classes(*args, **kwargs)

    def props(self, *args, **kwargs):
        """Apply Quasar props to widget"""
        return self.widget.props(*args, **kwargs)

    def style(self, *args, **kwargs):
        """Apply inline styles to widget"""
        return self.widget.style(*args, **kwargs)

    def __getattr__(self, name):
        """Proxy all other attributes to underlying widget"""
        return getattr(self.widget, name)


class DynamicDropDown(DynamicWidget):
    """Dropdown with auto-refreshing options"""

    def _normalize_options_for_select(self, options):
        """Normalize options to avoid NiceGUI select int payload edge cases."""
        # Track if this dropdown should store numeric-like values as strings.
        self._stringify_numeric_values = False

        if isinstance(options, list):
            if options and all(isinstance(v, (int, float)) for v in options):
                self._stringify_numeric_values = True
                return [str(v) for v in options]
            return options

        if isinstance(options, dict):
            # Keep labels as-is, but stringify numeric values (dict keys) for select safety.
            if options and all(isinstance(k, (int, float)) for k in options.keys()):
                self._stringify_numeric_values = True
                return {str(k): v for k, v in options.items()}
            return options

        return options

    def _coerce_value_for_select(self, value):
        if value is None:
            return None
        if getattr(self, "_stringify_numeric_values", False):
            return str(value)
        return value

    def _create_widget(self):
        """Create ui.select widget"""
        with_input = self.field_config.get("with_input", True)
        allow_custom = self.field_config.get("allow_custom", True)
        initial_options = self.field_config.get("options", [])

        # If options is a dict (parent-keyed map) or this widget has a parent,
        # start with empty options until the parent makes a selection.
        if isinstance(initial_options, dict) or self.parent:
            initial_options = []

        initial_options = self._normalize_options_for_select(initial_options)

        widget = ui.select(
            options=initial_options,
            label=self.label,
            with_input=with_input,
            **self.widget_kwargs,
        ).props("outlined")

        # Apply custom value mode if enabled
        if with_input and allow_custom:
            widget.props('new-value-mode="add-unique"')

        return widget

    async def _refresh_impl(self, parent_val):
        """Refresh dropdown options"""
        # Get fresh options from data fetcher
        new_options = await self.data_fetcher(self.options_source, parent_val)
        old_value = self._coerce_value_for_select(self.widget.value)

        # Guard: set options only for list/dict payloads
        if isinstance(new_options, (list, dict)):
            normalized_options = self._normalize_options_for_select(new_options)
            self.widget.options = normalized_options

            option_values = (
                set(normalized_options.keys())
                if isinstance(normalized_options, dict)
                else set(normalized_options)
            )

            if old_value and old_value not in option_values:
                self.widget.value = None
        else:
            # It's a plain value, not an options list — just set the value
            self.widget.value = self._coerce_value_for_select(new_options)

        # Apply default_source when widget has no value (e.g. after parent change)
        default_source = self.field_config.get("default_source")
        if default_source and not self.widget.value:
            default_val = await self.data_fetcher(default_source, parent_val)
            # A dict/list here means the source hasn't resolved to a single value
            # (e.g. no parent selected yet, so the whole parent-keyed map comes
            # back) — it's not a usable default and a dict is unhashable for the
            # membership test below.
            if default_val and not isinstance(default_val, (dict, list)):
                coerced_default = self._coerce_value_for_select(default_val)
                normalized_options = self.widget.options
                option_values = (
                    set(normalized_options.keys())
                    if isinstance(normalized_options, dict)
                    else set(normalized_options)
                ) if isinstance(normalized_options, (list, dict)) else set()
                if not option_values or coerced_default in option_values:
                    self.widget.value = coerced_default

        self.widget.update()

    @property
    def options(self):
        """Get current options"""
        return self.widget.options

    @options.setter
    def options(self, opts):
        """Set options"""
        self.widget.options = self._normalize_options_for_select(opts)


class DynamicInput(DynamicWidget):
    """Text input with auto-refresh from parent"""

    def _create_widget(self):
        """Create ui.input widget"""
        return ui.input(label=self.label, **self.widget_kwargs).props("outlined")

    async def _refresh_impl(self, parent_val):
        """Refresh input value based on parent"""
        if not parent_val:
            self.widget.value = ""
            return

        # Get fresh value from data fetcher
        new_value = await self.data_fetcher(self.options_source, parent_val)

        if isinstance(new_value, dict) and parent_val in new_value:
            self.widget.value = new_value[parent_val]
        elif isinstance(new_value, str):
            self.widget.value = new_value
        else:
            self.widget.value = ""

        self.widget.update()


class DynamicTextArea(DynamicWidget):
    """Multi-line text input"""

    def _create_widget(self):
        return ui.textarea(label=self.label, **self.widget_kwargs).props("outlined")

    async def _refresh_impl(self, parent_val):
        if not parent_val:
            self.widget.value = ""
            return
        new_value = await self.data_fetcher(self.options_source, parent_val)
        if isinstance(new_value, str):
            self.widget.value = new_value
        else:
            self.widget.value = ""
        self.widget.update()


class DynamicNumber(DynamicWidget):
    """Number input with auto-refresh from parent"""

    def _create_widget(self):
        """Create ui.number widget"""
        min_val = self.field_config.get("min")
        max_val = self.field_config.get("max")
        step = self.field_config.get("step", 1)

        widget = ui.number(
            label=self.label, min=min_val, max=max_val, step=step, **self.widget_kwargs
        ).props("outlined")

        return widget

    async def _refresh_impl(self, parent_val):
        """Refresh number value based on parent"""
        if not parent_val:
            self.widget.value = 0
            return

        # Get fresh value from data fetcher
        new_value = await self.data_fetcher(self.options_source, parent_val)

        if isinstance(new_value, dict) and parent_val in new_value:
            val = new_value[parent_val]
            # float, not int — int() silently truncated decimal values (e.g. wages)
            self.widget.value = float(val) if val is not None else 0
        elif isinstance(new_value, (int, float)):
            self.widget.value = new_value
        else:
            self.widget.value = 0

        self.widget.update()


class DynamicDateInput(DynamicWidget):
    """Date input with picker (using ui.input with date menu)"""

    def _create_widget(self):
        """Create ui.input with date picker menu"""
        default_val = self.field_config.get("default", date.today().isoformat())

        # Create input with date picker
        date_input = ui.input(
            label=self.label, value=default_val, **self.widget_kwargs
        ).props("readonly outlined")

        # Add date picker menu
        with date_input:
            with ui.menu().props("no-parent-event") as menu:
                with ui.date().bind_value(date_input):
                    with ui.row().classes("justify-end"):
                        ui.button("Close", on_click=menu.close).props("flat")
            with date_input.add_slot("append"):
                ui.icon("edit_calendar").on("click", menu.open).classes(
                    "cursor-pointer"
                )

        return date_input

    async def _refresh_impl(self, parent_val):
        """Refresh date value based on parent"""
        if not parent_val:
            self.widget.value = date.today().isoformat()
            return

        # Get fresh value from data fetcher
        new_value = await self.data_fetcher(self.options_source, parent_val)

        if isinstance(new_value, dict) and parent_val in new_value:
            self.widget.value = new_value[parent_val]
        elif isinstance(new_value, str):
            self.widget.value = new_value
        else:
            self.widget.value = date.today().isoformat()

        self.widget.update()


class DynamicDateTime(DynamicInput):
    """Plain-text datetime input (YYYY-MM-DD HH:MM:SS), e.g. time-table editing.

    Deliberately NOT type="datetime-local": DB values are stored/edited in the
    'YYYY-MM-DD HH:MM:SS' format, which a native datetime-local input rejects.
    """

    def _create_widget(self):
        return ui.input(
            label=self.label,
            placeholder="YYYY-MM-DD HH:MM:SS",
            **self.widget_kwargs,
        ).props("outlined")


class DynamicSwitch(DynamicWidget):
    """Switch/toggle with auto-refresh from parent"""

    def _create_widget(self):
        """Create ui.switch widget"""
        return ui.switch(text=self.label, **self.widget_kwargs)

    async def _refresh_impl(self, parent_val):
        """Refresh switch value based on parent"""
        if not parent_val:
            self.widget.value = False
            return

        # Get fresh value from data fetcher
        new_value = await self.data_fetcher(self.options_source, parent_val)

        if isinstance(new_value, dict) and parent_val in new_value:
            self.widget.value = bool(new_value[parent_val])
        elif isinstance(new_value, bool):
            self.widget.value = new_value
        else:
            self.widget.value = False

        self.widget.update()


class DynamicChipGroup(DynamicWidget):
    """Chip group for tags with auto-refresh options"""

    def _create_widget(self):
        """Create chip group for tags"""
        self._selected_tags = []
        # Normalize tags immediately to avoid serialization issues
        self._available_tags = self._normalize_tags(
            self.field_config.get("options", [])
        )

        # Create container (no label - just chips)
        self._chips_row = ui.row().classes("gap-1 flex-wrap w-full")

        # Render initial chips
        self._render_chips()

        return self._chips_row

    def _normalize_tags(self, tag_configs):
        """Convert DevOpsTagConfig objects to simple dicts to avoid serialization issues"""
        normalized = []
        for tag_config in tag_configs:
            if hasattr(tag_config, "name"):
                # It's a DevOpsTagConfig object - extract properties
                normalized.append(
                    {
                        "name": tag_config.name,
                        "color": getattr(tag_config, "color", "grey"),
                        "icon": getattr(tag_config, "icon", None),
                    }
                )
            elif isinstance(tag_config, dict):
                # Already a dict
                normalized.append(tag_config)
            else:
                # Plain string
                normalized.append(
                    {"name": str(tag_config), "color": "grey", "icon": None}
                )
        return normalized

    def _render_chips(self):
        """Render chip buttons with color and icon from config"""
        self._chips_row.clear()

        with self._chips_row:
            for tag_info in self._available_tags:
                tag_name = tag_info["name"]
                tag_color = tag_info.get("color", "grey")
                tag_icon = tag_info.get("icon")

                is_selected = tag_name in self._selected_tags

                # Use checkmark icon when selected, original icon otherwise
                display_icon = "check" if is_selected else tag_icon

                chip = ui.chip(
                    tag_name,
                    icon=display_icon,
                    on_click=lambda t=tag_name: self._toggle_tag(t),
                ).props("clickable")

                # Always use config color (not primary when selected)
                chip.style(
                    f"background: {tag_color} !important; color: white !important;"
                )
                chip.props("text-color=white")

    def _toggle_tag(self, tag):
        """Toggle tag selection"""
        if tag in self._selected_tags:
            self._selected_tags.remove(tag)
        else:
            self._selected_tags.append(tag)
        self._render_chips()

    async def _refresh_impl(self, parent_val):
        """Refresh available tags"""
        # Get fresh options from data fetcher
        new_options = await self.data_fetcher(self.options_source, parent_val)
        # Normalize immediately to avoid serialization issues
        self._available_tags = self._normalize_tags(new_options if new_options else [])
        self._render_chips()

    @property
    def value(self):
        """Get selected tags as comma-separated string"""
        return ", ".join(self._selected_tags)

    @value.setter
    def value(self, val):
        """Set selected tags from comma-separated string"""
        if isinstance(val, str):
            self._selected_tags = [t.strip() for t in val.split(",") if t.strip()]
        elif isinstance(val, list):
            self._selected_tags = val
        else:
            self._selected_tags = []

        if hasattr(self, "_chips_row"):
            self._render_chips()


class DynamicCodeMirror(DynamicWidget):
    """CodeMirror editor with auto-refresh and template support"""

    def _create_widget(self):
        """Create CodeMirror editor"""
        language = self.field_config.get("type_language", "markdown")
        templates = self.field_config.get("templates", {})
        default_val = self.field_config.get("default", "")

        # If templates exist, start with empty content (will be filled by template handling)
        if templates:
            default_val = ""

        # Replace template variables
        if default_val:
            default_val = default_val.replace("{today}", str(date.today()))

        editor = ui.codemirror(
            default_val,
            language=language,
            theme="dracula",
            line_wrapping=True,
        )

        # Store template info for later setup
        if templates:
            editor._template_info = {
                "templates": templates,
                "parent_fields": self.field_config.get("parent_fields", []),
            }
        return editor

    async def _refresh_impl(self, parent_val):
        """Refresh editor content based on parent"""
        if not parent_val:
            return

        new_value = await self.data_fetcher(self.options_source, parent_val)
        if isinstance(new_value, str):
            self.widget.value = new_value
            self.widget.update()


class DynamicHtml(DynamicWidget):
    """HTML preview widget with auto-refresh"""

    def _create_widget(self):
        """Create HTML preview widget"""
        default_val = self.field_config.get("default", "")

        # Get sizing from field config
        size_name = self.field_config.get("size", "standard")

        # Get HTML-specific styling from helpers
        try:
            from .. import helpers

            html_style = helpers.UI_STYLES.get_widget_style(
                "html_preview", "full" if size_name == "full" else "standard"
            )

            html_widget = ui.html(default_val, **self.widget_kwargs)

            # Apply classes and styles
            html_classes = html_style.get("base", "")
            if size_name == "full" and html_style.get("full_extra"):
                html_classes += f" {html_style['full_extra']}"

            if html_classes:
                html_widget.classes(html_classes)

            if html_style.get("style"):
                html_widget.style(html_style["style"])

            return html_widget
        except Exception:
            # Fallback if helpers not available
            return ui.html(default_val, **self.widget_kwargs)

    async def _refresh_impl(self, parent_val):
        """Refresh HTML content based on parent"""
        # Get parent value directly (for parent_update=True)
        if self.parent and hasattr(self.parent.widget, "value"):
            content = self.parent.widget.value or ""

            # Apply render function if specified
            render_fn_name = self.field_config.get("render_function")
            if render_fn_name:
                try:
                    from .. import helpers

                    if hasattr(helpers, render_fn_name):
                        render_fn = getattr(helpers, render_fn_name)
                        content = render_fn(content)
                except Exception as e:
                    logger.exception(f"Error rendering HTML preview for '{self.name}': {e}")

            # Update content - set it directly on the widget
            self.widget.set_content(content)
            self.widget.update()


class DynamicEditorWithPreview(DynamicWidget):
    """Combined code editor and preview widget with auto-refresh"""

    def _create_widget(self):
        """Create editor with side-by-side preview"""
        from .. import helpers

        language = self.field_config.get("language", "markdown")
        templates = self.field_config.get("templates")
        default_val = self.field_config.get("default", "")

        if templates:
            default_val = ""

        if default_val:
            default_val = default_val.replace("{today}", str(date.today()))

        self._container = ui.row().classes("gap-4 w-full")

        with self._container:
            with ui.column().classes("flex-1"):
                toolbar_holder = ui.element("div").classes("w-full")
                self._editor = (
                    ui.codemirror(
                        default_val,
                        language=language,
                        theme="dracula",
                        line_wrapping=True,
                    )
                    .classes("w-full")
                    .style("height: 400px; max-height: 400px; overflow: auto;")
                )
                self._toolbar_row = None
                if language == "markdown":
                    with toolbar_holder:
                        self._toolbar_row = render_markdown_toolbar(self._editor)

                if templates:
                    self._editor._template_info = {
                        "templates": templates,
                        "parent_fields": self.field_config.get("parent_fields", []),
                    }

            with ui.column().classes("flex-1"):
                html_style = helpers.UI_STYLES.get_widget_style("html_preview", "full")
                self._preview = ui.html("")

                html_classes = html_style.get("base", "")
                if html_style.get("full_extra"):
                    html_classes += f" {html_style['full_extra']}"
                if html_classes:
                    self._preview.classes(html_classes)
                if html_style.get("style"):
                    self._preview.style(html_style["style"])

                def update_preview(e):
                    content = self._editor.value or ""
                    render_fn_name = self.field_config.get("render_function")
                    if render_fn_name and hasattr(helpers, render_fn_name):
                        try:
                            render_fn = getattr(helpers, render_fn_name)
                            content = render_fn(content)
                        except Exception as ex:
                            logger.exception(f"Error rendering editor preview for '{self.name}': {ex}")
                    self._preview.set_content(content)

                self._editor.on_value_change(update_preview)

        return self._container

    def enable_image_upload(self, uploader, paste_endpoint=None, paste_fields=None):
        """Add an Insert-image button to the (already-rendered) toolbar and, if a
        paste endpoint is given, attach paste-to-upload. Called after the form is
        built, once the customer/context needed for uploads is known."""
        row = getattr(self, "_toolbar_row", None)
        if row is not None:
            with row:
                _render_image_button(self._editor, uploader)
        if paste_endpoint:
            inject_image_paste(self._editor, paste_endpoint, paste_fields or {})

    async def _refresh_impl(self, parent_val):
        """Refresh editor content based on parent"""
        if not parent_val:
            return

        new_value = await self.data_fetcher(self.options_source, parent_val)
        if isinstance(new_value, str):
            self._editor.value = new_value
            self._editor.update()

    @property
    def value(self):
        """Get editor value"""
        return self._editor.value if hasattr(self, "_editor") else ""

    @value.setter
    def value(self, val):
        """Set editor value"""
        if hasattr(self, "_editor"):
            self._editor.value = val

    def on_value_change(self, handler):
        """Register value change handler on the editor"""
        if hasattr(self, "_editor"):
            self._editor.on_value_change(handler)

    @property
    def widget(self):
        """Return the editor widget for compatibility with template handling"""
        return self._editor if hasattr(self, "_editor") else self._container

    @widget.setter
    def widget(self, val):
        """Allow widget assignment during initialization"""
        self._container = val


class DynamicMarkdown(DynamicWidget):
    """Markdown preview widget with auto-refresh"""

    def _create_widget(self):
        """Create markdown preview widget"""
        default_val = self.field_config.get("default", "")
        return ui.markdown(default_val, **self.widget_kwargs)

    async def _refresh_impl(self, parent_val):
        """Refresh markdown content based on parent"""
        # Get parent value directly (for parent_update=True)
        if self.parent and hasattr(self.parent.widget, "value"):
            content = self.parent.widget.value or ""
            self.widget.content = content
            self.widget.update()


_DEVOPS_LABEL_ID_RE = re.compile(r":\s*(\d+)\s*-")


def _coerce_git_id(val):
    """Convert a git-id value (int, float, numpy scalar, or numeric string) to a
    plain int, or None. Tolerates '1234.0' — a git_id column with any NULLs is
    read back from pandas as float, so row values arrive as e.g. 1234.0. A git id
    of 0 means "no work item", so it maps to None (blank field)."""
    if val in (None, ""):
        return None
    try:
        return int(float(val)) or None
    except (TypeError, ValueError):
        return None


def _devops_id_from_value(raw, label_to_id: dict):
    """Resolve a DevOps select value to a numeric git id (or None).

    `raw` is either a work-item label the user picked (mapped via label_to_id),
    a raw id typed straight in ("1234"), or a whole "Type: 1234 - Title" label
    typed by hand. Anything unparseable yields None, so the field clears rather
    than storing garbage.
    """
    if raw in (None, ""):
        return None
    if raw in label_to_id:
        return label_to_id[raw]
    s = str(raw).strip()
    if s.isdigit():
        return int(s)
    match = _DEVOPS_LABEL_ID_RE.search(s)
    return int(match.group(1)) if match else None


class DynamicDevOpsSelect(DynamicWidget):
    """Searchable dropdown of DevOps work items whose value is the numeric git id.

    Options are the work items for the relevant customer, fetched via the page's
    data_fetcher (which returns a list of {"label", "id"}). Picking an item
    stores its id. Degrades gracefully: the input accepts a hand-typed id, so it
    still works when DevOps is offline or the item isn't in the active set. When
    editing an existing value, the matching work item is preselected once the
    options load; if none matches, the raw id is shown instead.
    """

    def _create_widget(self):
        self._label_to_id: dict = {}
        self._desired_id = None  # id to (re)select once options arrive
        return (
            ui.select([], label=self.label, with_input=True, **self.widget_kwargs)
            .props('outlined new-value-mode="add-unique"')
            .classes("w-full")
        )

    def __init__(self, *args, **kwargs):
        # Capture the initial git id from the ARGUMENT, not from the widget: a
        # ui.select with an empty options list silently drops any value not in
        # its options, so self.widget.value would already read back None here.
        # (tolerating float columns like 1234.0). Options are loaded on parent
        # change (add/update forms) or by an explicit refresh() call (query-edit,
        # which has no parent field), at which point _apply_selection selects it.
        initial = kwargs.get("initial_value")
        if initial is None:
            initial = (kwargs.get("field_config") or {}).get("default")
        super().__init__(*args, **kwargs)
        self._desired_id = _coerce_git_id(initial)

    def _apply_selection(self):
        """Select the label matching _desired_id. If the current work item isn't
        in the option set (closed/done item, or DevOps offline), add a synthetic
        "#<id>" option and select THAT — a value not present in the select's
        options renders blank, so the option must exist for it to show."""
        if self._desired_id is None:
            self.widget.value = None
            self.widget.update()
            return
        for label, gid in self._label_to_id.items():
            if gid == self._desired_id:
                self.widget.value = label
                self.widget.update()
                return
        fallback = f"#{self._desired_id}"
        self._label_to_id[fallback] = self._desired_id
        self.widget.options = list(self._label_to_id.keys())
        self.widget.value = fallback
        self.widget.update()

    async def _refresh_impl(self, parent_val):
        data = await self.data_fetcher(self.options_source, parent_val)
        # Two response shapes:
        #   list -> options only (parent supplies the customer; value unchanged)
        #   {"items": [...], "current": id} -> options AND the value to select
        #       (Update-Project: parent is the project, so the current git id
        #       travels with its work-item options)
        has_current = isinstance(data, dict) and "items" in data
        options = data["items"] if has_current else data

        mapping: dict = {}
        if isinstance(options, list):
            for opt in options:
                if isinstance(opt, dict) and "label" in opt and "id" in opt:
                    mapping[str(opt["label"])] = int(opt["id"])
                elif isinstance(opt, (list, tuple)) and len(opt) == 2:
                    mapping[str(opt[0])] = int(opt[1])
        self._label_to_id = mapping
        self.widget.options = list(mapping.keys())

        if has_current:
            self._desired_id = _coerce_git_id(data.get("current"))
        self._apply_selection()

    @property
    def value(self):
        return _devops_id_from_value(self.widget.value, self._label_to_id)

    @value.setter
    def value(self, val):
        self._desired_id = _coerce_git_id(val)
        self._apply_selection()


class DynamicColor(DynamicWidget):
    """Hex colour picker with a swatch; refreshes from parent like DynamicInput."""

    def _create_widget(self):
        return ui.color_input(label=self.label, **self.widget_kwargs).props(
            "dense outlined"
        )

    async def _refresh_impl(self, parent_val):
        if not parent_val:
            self.widget.value = ""
            return
        new_value = await self.data_fetcher(self.options_source, parent_val)
        if isinstance(new_value, dict) and parent_val in new_value:
            self.widget.value = new_value[parent_val] or ""
        elif isinstance(new_value, str):
            self.widget.value = new_value
        else:
            self.widget.value = ""
        self.widget.update()


# Widget type registry - maps field types to widget classes
WIDGET_CLASSES = {
    "select": DynamicDropDown,
    "input": DynamicInput,
    "text": DynamicTextArea,  # multi-line, matching the legacy make_input_row behavior
    "textarea": DynamicTextArea,
    "number": DynamicNumber,
    "color": DynamicColor,
    "devops_id": DynamicDevOpsSelect,
    "date": DynamicDateInput,
    "datetime": DynamicDateTime,
    "switch": DynamicSwitch,
    "chip_group": DynamicChipGroup,
    "codemirror": DynamicCodeMirror,
    "html": DynamicHtml,
    "markdown": DynamicMarkdown,
    "editor_with_preview": DynamicEditorWithPreview,
}
