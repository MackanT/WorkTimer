"""
Notepad Page

A markdown-based notepad with a VS Code-style sidebar for managing multiple notes.
Notes are stored as .md files on disk. Auto-saves on edit with debounce.
Click anywhere on the rendered markdown to switch to split editor+preview mode.
Escape to return to view mode.
"""

import re
from pathlib import Path

from nicegui import ui

from ..core.app import AppCore
from ..ui.elements import toolbar, page_card
from ..helpers import render_and_sanitize_markdown


def get_notes_dir() -> Path:
    """Get notes directory — data/notes relative to project root."""
    project_root = Path(__file__).resolve().parent.parent.parent
    path = project_root / "data" / "notes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def title_from_content(content: str, filename: str) -> str:
    """Extract # Title from markdown content, fall back to filename stem."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return Path(filename).stem.replace("-", " ").replace("_", " ").title()


def filename_from_title(title: str) -> str:
    """Convert a title to a safe filename."""
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return f"{slug or 'untitled'}.md"


def load_notes(notes_dir: Path) -> list[dict]:
    """Load all .md files from notes directory."""
    notes = []
    for f in sorted(notes_dir.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        notes.append(
            {
                "filename": f.name,
                "title": title_from_content(content, f.name),
                "content": content,
            }
        )
    return notes


def save_note(notes_dir: Path, filename: str, content: str) -> str:
    """
    Save note content to disk. If # Title changed, rename the file.
    Returns the (possibly new) filename.
    """
    new_title = title_from_content(content, filename)
    new_filename = filename_from_title(new_title)
    old_path = notes_dir / filename
    new_path = notes_dir / new_filename

    if old_path.exists() and new_filename != filename:
        old_path.rename(new_path)

    new_path.write_text(content, encoding="utf-8")
    return new_filename


def create_note(notes_dir: Path) -> dict:
    """Create a new untitled note on disk and return its metadata."""
    base = "untitled"
    filename = f"{base}.md"
    counter = 1
    while (notes_dir / filename).exists():
        filename = f"{base}-{counter}.md"
        counter += 1

    content = "# Untitled\n\n"
    (notes_dir / filename).write_text(content, encoding="utf-8")
    return {"filename": filename, "title": "Untitled", "content": content}


def delete_note(notes_dir: Path, filename: str):
    """Delete a note file from disk."""
    path = notes_dir / filename
    if path.exists():
        path.unlink()


async def notepad_page():
    """Notepad page — markdown notes with file-based storage."""
    core = await AppCore.get_or_initialize()
    notes_dir = get_notes_dir()

    # ── Page state ────────────────────────────────────────────────────────────
    state = {
        "notes": load_notes(notes_dir),
        "active_index": 0,
        "edit_mode": False,
        "save_timer": None,
        "toolbar_container": None,
        "sidebar_container": None,
        "content_area": None,
    }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def active_note() -> dict | None:
        notes = state["notes"]
        idx = state["active_index"]
        return notes[idx] if notes and 0 <= idx < len(notes) else None

    def schedule_save(content: str):
        """Debounced save — waits 1s after last keystroke."""
        if state["save_timer"]:
            state["save_timer"].cancel()

        async def _do_save():
            note = active_note()
            if not note:
                return
            new_filename = save_note(notes_dir, note["filename"], content)
            old_filename = note["filename"]
            note["content"] = content
            note["title"] = title_from_content(content, new_filename)
            note["filename"] = new_filename
            if new_filename != old_filename:
                render_sidebar()
            else:
                render_sidebar()

        state["save_timer"] = ui.timer(1.0, _do_save, once=True)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render_toolbar_bar():
        """Re-render toolbar — needed to update the edit mode hint."""
        state["toolbar_container"].clear()
        with state["toolbar_container"]:
            with toolbar(core.theme):
                ui.icon("note", size="md").classes("text-amber-400")
                ui.label("Notepad").classes("text-h5 text-white font-medium")
                ui.space()
                if state["edit_mode"]:
                    ui.label("Esc to exit edit mode").classes(
                        "text-xs text-gray-400 italic"
                    )
                ui.button(icon="add", on_click=new_note).props(
                    "flat dense color=primary"
                ).tooltip("New Note")
                ui.button(icon="delete", on_click=delete_active_note).props(
                    "flat dense color=primary"
                ).tooltip("Delete Note")

    def render_sidebar():
        """Render the notes list sidebar."""
        container = state["sidebar_container"]
        if not container:
            return
        container.clear()

        with container:
            for i, note in enumerate(state["notes"]):
                is_active = i == state["active_index"]
                row_classes = (
                    "w-full flex items-center gap-2 px-3 py-2 rounded cursor-pointer "
                    + (
                        "bg-amber-400 text-black font-medium"
                        if is_active
                        else "hover:bg-gray-100 dark:hover:bg-gray-700"
                    )
                )
                with (
                    ui.row()
                    .classes(row_classes)
                    .on("click", lambda _, idx=i: select_note(idx))
                ):
                    ui.icon("description", size="xs")
                    ui.label(note["title"] or "Untitled").classes(
                        "text-sm truncate flex-1"
                    )

    def render_content():
        """Render the main content area (view or edit mode)."""
        container = state["content_area"]
        if not container:
            return
        container.clear()

        note = active_note()
        if not note:
            with container:
                ui.label("No notes yet — create one!").classes(
                    "text-gray-400 text-center w-full mt-16"
                )
            return

        with container:
            if state["edit_mode"]:
                _render_edit_mode(note)
            else:
                _render_view_mode(note)

    def _render_view_mode(note: dict):
        """Rendered markdown — click anywhere to enter edit mode."""
        content = note["content"] or "*Empty note — click to start writing*"

        html_view = (
            ui.html(render_and_sanitize_markdown(content))
            .classes("w-full cursor-text")
            .style("min-height: 200px;")
        )
        html_view.on("click", lambda _: enter_edit_mode())

        ui.keyboard(on_key=lambda e: exit_edit_mode() if e.key == "Escape" else None)

    def _render_edit_mode(note: dict):
        """Split editor + live preview."""
        with ui.row().classes("w-full gap-0").style("height: calc(100vh - 200px);"):
            # Left: CodeMirror editor
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

            # Right: live preview
            with ui.column().classes("flex-1 h-full overflow-auto p-4"):
                preview = ui.html(
                    render_and_sanitize_markdown(note["content"])
                ).classes("w-full")

            def on_change(e):
                content = editor.value or ""
                note["content"] = content
                schedule_save(content)
                preview.set_content(render_and_sanitize_markdown(content))

            editor.on_value_change(on_change)

        ui.keyboard(on_key=lambda e: exit_edit_mode() if e.key == "Escape" else None)

    # ── State transitions ─────────────────────────────────────────────────────

    def select_note(index: int):
        state["active_index"] = index
        state["edit_mode"] = False
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
        delete_note(notes_dir, note["filename"])
        state["notes"].pop(state["active_index"])
        if state["notes"]:
            state["active_index"] = max(0, state["active_index"] - 1)
        else:
            state["active_index"] = 0
        state["edit_mode"] = False
        render_toolbar_bar()
        render_sidebar()
        render_content()

    # ── UI Layout ─────────────────────────────────────────────────────────────

    # Toolbar container — rendered outside page_card so it sits at top
    state["toolbar_container"] = ui.column().classes("w-full")
    render_toolbar_bar()

    with page_card():
        with ui.row().classes("w-full gap-0").style("height: calc(100vh - 160px);"):
            # Sidebar
            with ui.column().classes(
                "w-48 shrink-0 border-r dark:border-gray-700 overflow-y-auto p-2 gap-1"
            ):
                state["sidebar_container"] = ui.column().classes("w-full gap-1")

            # Main content
            with ui.column().classes("flex-1 overflow-auto p-6"):
                state["content_area"] = ui.column().classes("w-full h-full")

    # ── Initial render ────────────────────────────────────────────────────────
    render_sidebar()
    render_content()
