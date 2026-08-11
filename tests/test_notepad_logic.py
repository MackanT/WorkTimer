"""Tests for pure note-file helpers in src/pages/notepad.py."""

from src.pages.notepad import (
    filename_from_title,
    save_note,
    title_from_content,
    toggle_checkbox_in_content,
)


def test_toggle_checkbox_roundtrip():
    assert toggle_checkbox_in_content("- [ ] a", 0) == "- [x] a"
    assert toggle_checkbox_in_content("- [x] a", 0) == "- [ ] a"


def test_toggle_checkbox_second_item():
    src = "- [ ] a\n- [ ] b"
    assert toggle_checkbox_in_content(src, 1) == "- [ ] a\n- [x] b"


def test_toggle_checkbox_out_of_range_is_noop():
    assert toggle_checkbox_in_content("- [ ] a", 5) == "- [ ] a"


def test_title_from_heading():
    assert title_from_content("# Hello World\nbody", "f.md") == "Hello World"


def test_title_falls_back_to_filename():
    assert title_from_content("no heading here", "my-cool-note.md") == "My Cool Note"


def test_filename_from_title():
    assert filename_from_title("Hello World") == "hello-world.md"
    assert filename_from_title("Weird!!! Chars??") == "weird-chars.md"
    assert filename_from_title("") == "untitled.md"


def test_save_note_avoids_collision(tmp_path):
    """Renaming onto another note's file must suffix, never overwrite (§1.4)."""
    (tmp_path / "ideas.md").write_text("# Ideas\noriginal", encoding="utf-8")
    (tmp_path / "untitled.md").write_text("# Untitled\n", encoding="utf-8")

    note = {"filename": "untitled.md", "external": False}
    new_name = save_note(tmp_path, note, "# Ideas\nbrand new")

    assert new_name == "ideas-1.md"
    # The pre-existing note is untouched.
    assert (tmp_path / "ideas.md").read_text(encoding="utf-8") == "# Ideas\noriginal"
    assert (tmp_path / "ideas-1.md").read_text(encoding="utf-8") == "# Ideas\nbrand new"
    assert not (tmp_path / "untitled.md").exists()


def test_save_note_same_name_overwrites_self(tmp_path):
    (tmp_path / "notes.md").write_text("# Notes\nv1", encoding="utf-8")
    note = {"filename": "notes.md", "external": False}
    new_name = save_note(tmp_path, note, "# Notes\nv2")
    assert new_name == "notes.md"
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "# Notes\nv2"
