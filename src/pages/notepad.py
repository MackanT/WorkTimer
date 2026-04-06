"""
Notepad Page

A markdown-based notepad with a VS Code-style sidebar for managing multiple notes.
Notes are stored as .md files on disk. Auto-saves on edit with debounce.
Click anywhere on the rendered markdown to switch to split editor+preview mode.
Escape to return to view mode.

Features:
- Sidebar with search, color tags, pin, groups
- External pinned files (e.g. docs/todo.md) — read/write but no rename
- Auto-save with debounce
- Note metadata stored in data/notes/notes_meta.json
"""

import json
import re
from pathlib import Path
import time
from fastapi import UploadFile, Request, File
from nicegui import ui, app

from ..core.app import AppCore
from ..ui.elements import toolbar, page_card, toolbar_divider, PAGE_HEIGHT
from ..helpers import render_and_sanitize_markdown, UI_STYLES


# ── Constants ─────────────────────────────────────────────────────────────────

NOTE_COLORS = {
    "none": {"bg": "", "dot": "bg-gray-400"},
    "amber": {"bg": "border-l-4 border-amber-400", "dot": "bg-amber-400"},
    "red": {"bg": "border-l-4 border-red-400", "dot": "bg-red-400"},
    "green": {"bg": "border-l-4 border-green-400", "dot": "bg-green-400"},
    "blue": {"bg": "border-l-4 border-blue-400", "dot": "bg-blue-400"},
    "purple": {"bg": "border-l-4 border-purple-400", "dot": "bg-purple-400"},
}

NOTE_ICONS = {
    "note": "description",
    "todo": "check_box",
    "idea": "lightbulb",
    "warning": "warning",
    "star": "star",
    "link": "link",  # used for external files
}

# External pinned files — path relative to project root, display name, locked name
EXTERNAL_NOTES = [
    {
        "path": "docs/todo.md",
        "display_name": "Todo",
        "icon": "todo",
        "readonly_name": True,
        "developer_only": True,
    },
]


# ── Path helpers ───────────────────────────────────────────────────────────────


def get_notes_dir() -> Path:
    project_root = Path(__file__).resolve().parent.parent.parent
    path = project_root / "data" / "notes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


# ── Metadata ──────────────────────────────────────────────────────────────────


def load_meta(notes_dir: Path) -> dict:
    """Load notes_meta.json — {filename: {color, icon, pinned, group}}"""
    meta_path = notes_dir / "notes_meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_meta(notes_dir: Path, meta: dict):
    meta_path = notes_dir / "notes_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def get_note_meta(meta: dict, filename: str) -> dict:
    return meta.get(
        filename, {"color": "none", "icon": "note", "pinned": False, "group": ""}
    )


def update_note_meta(notes_dir: Path, meta: dict, filename: str, **kwargs):
    if filename not in meta:
        meta[filename] = {"color": "none", "icon": "note", "pinned": False, "group": ""}
    meta[filename].update(kwargs)
    save_meta(notes_dir, meta)


# ── Note file helpers ──────────────────────────────────────────────────────────


def title_from_content(content: str, filename: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return Path(filename).stem.replace("-", " ").replace("_", " ").title()


def filename_from_title(title: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return f"{slug or 'untitled'}.md"


def load_notes(notes_dir: Path, meta: dict) -> list[dict]:
    """Load all regular .md files (excluding notes_meta.json)."""
    notes = []
    for f in sorted(notes_dir.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        note_meta = get_note_meta(meta, f.name)
        notes.append(
            {
                "filename": f.name,
                "title": title_from_content(content, f.name),
                "content": content,
                "external": False,
                "readonly_name": False,
                **note_meta,
            }
        )

    # Sort: pinned first, then alphabetical
    notes.sort(key=lambda n: (not n.get("pinned", False), n["title"].lower()))
    return notes


def load_external_notes(project_root: Path, meta: dict, developer_mode: bool = False) -> list[dict]:
    """Load hardcoded external notes. Developer-only notes are excluded unless developer_mode is True."""
    notes = []
    for ext in EXTERNAL_NOTES:
        if ext.get("developer_only") and not developer_mode:
            continue
        path = project_root / ext["path"]
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {ext['display_name']}\n\n", encoding="utf-8")
        content = path.read_text(encoding="utf-8")
        note_meta = get_note_meta(meta, ext["path"])
        notes.append(
            {
                "filename": ext["path"],  # use full relative path as key
                "title": ext["display_name"],
                "content": content,
                "external": True,
                "readonly_name": ext.get("readonly_name", True),
                "abs_path": path,
                "color": note_meta.get("color", "none"),
                "icon": ext.get("icon", "note"),
                "pinned": note_meta.get("pinned", False),
                "group": note_meta.get("group", ""),
            }
        )
    return notes


def save_note(notes_dir: Path, note: dict, content: str) -> str:
    """Save note. Handles rename for regular notes. Returns new filename."""
    if note["external"]:
        note["abs_path"].write_text(content, encoding="utf-8")
        return note["filename"]

    new_title = title_from_content(content, note["filename"])
    new_filename = filename_from_title(new_title)
    old_path = notes_dir / note["filename"]
    new_path = notes_dir / new_filename

    if old_path.exists() and new_filename != note["filename"]:
        old_path.rename(new_path)

    new_path.write_text(content, encoding="utf-8")
    return new_filename


def create_note(notes_dir: Path) -> dict:
    base = "untitled"
    filename = f"{base}.md"
    counter = 1
    while (notes_dir / filename).exists():
        filename = f"{base}-{counter}.md"
        counter += 1
    content = "# Untitled\n\n"
    (notes_dir / filename).write_text(content, encoding="utf-8")
    return {
        "filename": filename,
        "title": "Untitled",
        "content": content,
        "external": False,
        "readonly_name": False,
        "color": "none",
        "icon": "note",
        "pinned": False,
        "group": "",
    }


def delete_note(notes_dir: Path, note: dict):
    if note["external"]:
        return  # never delete external files
    path = notes_dir / note["filename"]
    if path.exists():
        path.unlink()


# ── Image Upload Endpoint ───────────────────────────────────────────────


@app.post("/upload_image")
async def upload_image(request: Request, file: UploadFile = File(...)):
    notes_dir = get_notes_dir()

    form = await request.form()
    note_filename = form.get("note")

    if not note_filename:
        return {"error": "Missing note filename"}

    note_stem = Path(note_filename).stem
    assets_dir = notes_dir / f"{note_stem}_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix or ".png"
    filename = f"img_{int(time.time() * 1000)}{ext}"
    file_path = assets_dir / filename

    content = await file.read()
    file_path.write_bytes(content)

    return {"path": f"/notes_assets/{note_stem}_assets/{filename}"}


app.add_static_files("/notes_assets", str(get_notes_dir()))

# ── Main page ──────────────────────────────────────────────────────────────────


async def notepad_page():
    core = await AppCore.get_or_initialize()
    notes_dir = get_notes_dir()
    project_root = get_project_root()

    meta = load_meta(notes_dir)
    regular_notes = load_notes(notes_dir, meta)
    external_notes = load_external_notes(project_root, meta, developer_mode=core.settings.developer_mode)
    all_notes = external_notes + regular_notes

    state = {
        "notes": all_notes,
        "active_index": 0,
        "edit_mode": False,
        "save_timer": None,
        "search_query": "",
        "toolbar_container": None,
        "sidebar_container": None,
        "content_area": None,
        "meta": meta,
    }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def active_note() -> dict | None:
        notes = state["notes"]
        idx = state["active_index"]
        return notes[idx] if notes and 0 <= idx < len(notes) else None

    def filtered_notes() -> list[tuple[int, dict]]:
        """Return (original_index, note) pairs matching search query."""
        q = state["search_query"].lower().strip()
        return [
            (i, n)
            for i, n in enumerate(state["notes"])
            if not q or q in n["title"].lower() or q in n["content"].lower()
        ]

    def schedule_save(content: str):
        if state["save_timer"]:
            state["save_timer"].cancel()

        async def _do_save():
            note = active_note()
            if not note:
                return
            old_filename = note["filename"]
            new_filename = save_note(notes_dir, note, content)
            note["content"] = content
            note["filename"] = new_filename

            if not note["readonly_name"]:
                note["title"] = title_from_content(content, new_filename)

            # Rename meta key if filename changed
            if new_filename != old_filename and old_filename in state["meta"]:
                state["meta"][new_filename] = state["meta"].pop(old_filename)
                save_meta(notes_dir, state["meta"])

            render_toolbar_bar()
            render_sidebar()

        state["save_timer"] = ui.timer(1.0, _do_save, once=True)

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def collapse_all_groups():
        all_groups = {n.get("group", "") for n in state["notes"] if n.get("group")}
        state["collapsed_groups"] = all_groups
        render_sidebar()

    def expand_all_groups():
        state["collapsed_groups"] = set()
        render_sidebar()

    def render_toolbar_bar():
        state["toolbar_container"].clear()
        with state["toolbar_container"]:
            with toolbar(core.theme):
                ui.icon("note", size="md").classes(f"text-{core.theme.get('accent')}")
                ui.label("Notepad").classes(UI_STYLES.get_layout_classes("page_title"))
                ui.space()

                if state["edit_mode"]:
                    ui.label("Esc to exit edit mode").classes(
                        UI_STYLES.get_layout_classes("muted_text_xs_italic")
                    )
                    ui.space()

                # Collapse all groups
                ui.button(icon="unfold_less", on_click=collapse_all_groups).props(
                    "flat dense color=primary"
                ).tooltip("Collapse all groups")

                # Expand all groups
                ui.button(icon="unfold_more", on_click=expand_all_groups).props(
                    "flat dense color=primary"
                ).tooltip("Expand all groups")

                toolbar_divider(core.theme)

                ui.button(icon="add", on_click=new_note).props(
                    "flat dense color=primary"
                ).tooltip("New Note")
                ui.button(icon="delete", on_click=delete_active_note).props(
                    "flat dense color=negative"
                ).tooltip("Delete Note")

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def toggle_group_collapse(group_name: str):
        if group_name in state["collapsed_groups"]:
            state["collapsed_groups"].discard(group_name)
        else:
            state["collapsed_groups"].add(group_name)
        render_sidebar()

    def render_sidebar():
        container = state["sidebar_container"]
        if not container:
            return
        container.clear()

        with container:
            visible = filtered_notes()
            if not visible:
                ui.label("No notes found").classes(
                    UI_STYLES.get_layout_classes("muted_text_xs") + " text-center w-full mt-4"
                )
                return

            groups: dict[str, list] = {}
            for orig_idx, note in visible:
                group = note.get("group") or ""
                groups.setdefault(group, []).append((orig_idx, note))

            for group_name, group_notes in groups.items():
                if group_name:
                    is_collapsed = group_name in state["collapsed_groups"]
                    with (
                        ui.row()
                        .classes(
                            "w-full items-center gap-1 mt-2 mb-1 px-1 cursor-pointer"
                        )
                        .on("click", lambda _, g=group_name: toggle_group_collapse(g))
                    ):
                        ui.icon(
                            "chevron_right" if is_collapsed else "expand_more",
                            size="xs",
                        ).classes(UI_STYLES.get_layout_classes("muted_text"))
                        ui.label(group_name).classes(
                            UI_STYLES.get_layout_classes("group_header_text")
                        )
                        ui.separator().classes("flex-1")

                    if is_collapsed:
                        continue  # skip rendering notes in this group

                for orig_idx, note in group_notes:
                    is_active = orig_idx == state["active_index"]
                    color_info = NOTE_COLORS.get(
                        note.get("color", "none"), NOTE_COLORS["none"]
                    )
                    icon_name = NOTE_ICONS.get(note.get("icon", "note"), "description")

                    base_classes = (
                        "w-full flex items-center gap-2 px-2 py-2 rounded cursor-pointer "
                        + color_info["bg"]
                        + " "
                        + (
                            f"bg-{core.theme.get('accent')} text-black font-medium"
                            if is_active
                            else "hover:bg-gray-100 dark:hover:bg-gray-700"
                        )
                    )

                    with (
                        ui.row()
                        .classes(base_classes)
                        .on("click", lambda _, idx=orig_idx: select_note(idx))
                    ):
                        if note.get("pinned"):
                            ui.icon("push_pin", size="xs").classes(
                                f"text-{core.theme.get('accent')} rotate-45"
                            )
                        ui.icon(icon_name, size="xs")
                        ui.label(note["title"] or "Untitled").classes(
                            "text-sm truncate flex-1"
                        )
                        if note.get("color", "none") != "none":
                            ui.element("div").classes(
                                f"w-2 h-2 rounded-full shrink-0 {color_info['dot']}"
                            )

                        with ui.context_menu().classes(
                            f"border border-{core.theme.get('accent')} rounded"
                        ):
                            ui.label("Color").classes(UI_STYLES.get_layout_classes("context_menu_label"))
                            with ui.row().classes("px-2 pb-1 gap-1"):
                                for color_key, color_val in NOTE_COLORS.items():
                                    ui.element("div").classes(
                                        f"w-4 h-4 rounded-full cursor-pointer {color_val['dot']} "
                                        "hover:scale-125 transition-transform"
                                    ).on(
                                        "click",
                                        lambda _, ck=color_key, fn=note["filename"]: (
                                            set_note_color(fn, ck)
                                        ),
                                    )
                            ui.separator()
                            ui.label("Icon").classes(UI_STYLES.get_layout_classes("context_menu_label"))
                            for icon_key, icon_val in NOTE_ICONS.items():
                                if icon_key == "link":
                                    continue
                                ui.menu_item(
                                    icon_key.capitalize(),
                                    on_click=lambda _, ik=icon_key, fn=note["filename"]: (
                                        set_note_icon(fn, ik)
                                    ),
                                ).props(f"icon={icon_val}")
                            ui.separator()
                            pin_label = "Unpin" if note.get("pinned") else "Pin to top"
                            ui.menu_item(
                                pin_label,
                                on_click=lambda _, fn=note["filename"]: toggle_pin(fn),
                            ).props("icon=push_pin")
                            ui.separator()
                            ui.label("Group").classes(UI_STYLES.get_layout_classes("context_menu_label"))
                            group_input = (
                                ui.input(
                                    placeholder="Group name...",
                                    value=note.get("group", ""),
                                )
                                .props("dense outlined")
                                .classes("w-full px-2 pb-1")
                            )
                            group_input.on(
                                "keydown.enter",
                                lambda _, fn=note["filename"], gi=group_input: (
                                    set_note_group(fn, gi.value)
                                ),
                            )

    def on_search_change(value: str):
        state["search_query"] = value or ""
        render_sidebar()

    # ── Content ───────────────────────────────────────────────────────────────

    def render_content():
        container = state["content_area"]
        if not container:
            return
        container.clear()

        note = active_note()
        if not note:
            with container:
                ui.label("No notes yet \u2014 create one!").classes(
                    UI_STYLES.get_layout_classes("muted_text_center_tall")
                )
            return
        with container:
            if state["edit_mode"]:
                _render_edit_mode(note)
            else:
                _render_view_mode(note)

    def _render_view_mode(note: dict):
        content = note["content"] or "*Empty note — click to start writing*"
        html_view = (
            ui.html(render_and_sanitize_markdown(content))
            .classes("w-full cursor-text")
            .style("min-height: 200px; margin-top: 0; padding-top: 0;")
        )
        html_view.on("click", lambda _: enter_edit_mode())
        ui.keyboard(on_key=lambda e: exit_edit_mode() if e.key == "Escape" else None)

    def _render_edit_mode(note: dict):
        with ui.row().classes("w-full gap-0").style("height: 100%;"):
            # Left: editor
            with ui.column().classes("flex-1 h-full border-r dark:border-gray-700"):
                editor = (
                    ui.codemirror(
                        note["content"],
                        language="markdown",
                        theme="dracula",
                        line_wrapping=True,
                    )
                    .classes("w-full h-full")
                    .style("height: 100%;")
                )

                editor_id = editor.id
                state["active_editor"] = editor_id

                def inject_paste_handler():
                    editor_id = state.get("active_editor")
                    note_filename = active_note()["filename"] if active_note() else ""

                    if not editor_id or not note_filename:
                        return

                    ui.run_javascript(f"""
                        let attempts = 0;
                        const maxAttempts = 20;
                        
                        function tryAttach() {{
                            attempts++;
                            const cmEditors = document.querySelectorAll('.cm-editor');
                            console.log(`Attempt ${{attempts}}: found ${{cmEditors.length}} CM editors`);
                            
                            if (!cmEditors.length) {{
                                if (attempts < maxAttempts) {{
                                    setTimeout(tryAttach, 200);
                                }} else {{
                                    console.warn("Gave up finding CodeMirror editor after " + maxAttempts + " attempts");
                                }}
                                return;
                            }}

                            const cmEl = cmEditors[cmEditors.length - 1];

                            if (cmEl._imagePasteEnabled) {{
                                console.log("Paste handler already attached");
                                return;
                            }}
                            cmEl._imagePasteEnabled = true;
                            console.log("Paste handler attached to CM editor");

                            cmEl.addEventListener('paste', async (event) => {{
                                const items = event.clipboardData?.items;
                                if (!items) return;

                                for (const item of items) {{
                                    if (!item.type.startsWith('image/')) continue;

                                    event.preventDefault();
                                    console.log("Image paste detected, uploading...");

                                    const blob = item.getAsFile();
                                    const formData = new FormData();
                                    formData.append('file', blob, 'paste.png');
                                    formData.append('note', "{note_filename}");

                                    try {{
                                        const response = await fetch('/upload_image', {{
                                            method: 'POST',
                                            body: formData
                                        }});

                                        if (!response.ok) {{
                                            console.error("Upload failed:", await response.text());
                                            return;
                                        }}

                                        const data = await response.json();
                                        console.log("Upload response:", data);
                                        if (!data.path) return;

                                        const md = `![image](${{data.path}})\\n`;
                                        console.log("Inserting markdown:", md);

                                        // Access the CodeMirror 6 EditorView via the
                                        // internal cmView property on the contentDOM.
                                        const cmContent = cmEl.querySelector('.cm-content');
                                        const view = cmContent?.cmView?.view;

                                        if (view && typeof view.dispatch === 'function') {{
                                            view.dispatch(view.state.replaceSelection(md));
                                            view.focus();
                                        }} else {{
                                            // Fallback: works in Firefox
                                            cmContent?.focus();
                                            document.execCommand('insertText', false, md);
                                        }}

                                    }} catch (err) {{
                                        console.error("Upload error:", err);
                                    }}
                                }}
                            }});
                        }}
                        
                        tryAttach();
                    """)

                ui.timer(0.1, inject_paste_handler, once=True)

            # Right: preview
            with ui.column().classes("flex-1 h-full overflow-auto p-4"):
                preview = (
                    ui.html(render_and_sanitize_markdown(note["content"]))
                    .classes("w-full")
                    .style("margin-top: 0; padding-top: 0;")
                )

            def on_change(e):
                content = editor.value or ""
                note["content"] = content
                schedule_save(content)
                preview.set_content(render_and_sanitize_markdown(content))

            editor.on_value_change(on_change)

        ui.keyboard(on_key=lambda e: exit_edit_mode() if e.key == "Escape" else None)

    # ── Note actions ──────────────────────────────────────────────────────────

    def set_note_color(filename: str, color: str):
        update_note_meta(notes_dir, state["meta"], filename, color=color)
        note = next((n for n in state["notes"] if n["filename"] == filename), None)
        if note:
            note["color"] = color
        render_sidebar()

    def set_note_icon(filename: str, icon: str):
        update_note_meta(notes_dir, state["meta"], filename, icon=icon)
        note = next((n for n in state["notes"] if n["filename"] == filename), None)
        if note:
            note["icon"] = icon
        render_sidebar()

    def toggle_pin(filename: str):
        note = next((n for n in state["notes"] if n["filename"] == filename), None)
        if not note:
            return
        new_pinned = not note.get("pinned", False)
        update_note_meta(notes_dir, state["meta"], filename, pinned=new_pinned)
        note["pinned"] = new_pinned
        # Re-sort: pinned notes float to top
        ext = [n for n in state["notes"] if n["external"]]
        reg = [n for n in state["notes"] if not n["external"]]
        reg.sort(key=lambda n: (not n.get("pinned", False), n["title"].lower()))
        state["notes"] = ext + reg
        # Restore active index after re-sort
        active = active_note()
        if active:
            state["active_index"] = state["notes"].index(active)
        render_sidebar()

    def set_note_group(filename: str, group: str):
        update_note_meta(notes_dir, state["meta"], filename, group=group.strip())
        note = next((n for n in state["notes"] if n["filename"] == filename), None)
        if note:
            note["group"] = group.strip()
        render_sidebar()

    def select_note(index: int):
        state["active_index"] = index
        state["edit_mode"] = False
        render_toolbar_bar()
        render_sidebar()
        render_content()

    def enter_edit_mode():
        state["edit_mode"] = True
        render_toolbar_bar()
        render_content()

    def exit_edit_mode():
        state["edit_mode"] = False
        render_toolbar_bar()
        render_content()

    async def new_note():
        note = create_note(notes_dir)
        state["notes"].append(note)
        state["active_index"] = len(state["notes"]) - 1
        state["edit_mode"] = True
        render_toolbar_bar()
        render_sidebar()
        render_content()

    async def delete_active_note():
        note = active_note()
        if not note:
            return
        if note["external"]:
            ui.notify("External notes cannot be deleted.", type="warning")
            return
        delete_note(notes_dir, note)
        state["notes"].pop(state["active_index"])
        state["active_index"] = (
            max(0, state["active_index"] - 1) if state["notes"] else 0
        )
        state["edit_mode"] = False
        render_toolbar_bar()
        render_sidebar()
        render_content()

    # ── Layout ────────────────────────────────────────────────────────────────

    state["toolbar_container"] = ui.column().classes("w-full")
    state["collapsed_groups"] = set()
    render_toolbar_bar()

    with page_card(scrollable=False):
        with (
            ui.row()
            .classes("w-full gap-0 overflow-hidden")
            .style("flex: 1; min-height: 0;")
        ):
            with (
                ui.column()
                .classes(
                    "w-52 shrink-0 border-r dark:border-gray-700 overflow-y-auto p-2 gap-1"
                )
                .style("height: 100%;")
            ):
                # Search input — created once here, never moved or recreated
                ui.input(
                    placeholder="Search notes...",
                    on_change=lambda e: on_search_change(e.value),
                ).props("dense outlined clearable").classes("w-full mb-2")

                # Notes list container — only this gets cleared/re-rendered
                state["sidebar_container"] = ui.column().classes("w-full gap-1")

            # Main content
            with ui.column().classes("flex-1 overflow-auto p-6").style("height: 100%;"):
                state["content_area"] = ui.column().classes("w-full")

    render_sidebar()
    render_content()
