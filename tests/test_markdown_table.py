"""Tests for the markdown-table builder (src/ui/dynamic_widgets.build_markdown_table)."""

from src.ui.dynamic_widgets import build_markdown_table


def test_basic_table_default_left_align():
    md = build_markdown_table(["A", "B"], [["1", "2"], ["3", "4"]])
    assert md == "| A | B |\n| :--- | :--- |\n| 1 | 2 |\n| 3 | 4 |"


def test_alignment_separators():
    md = build_markdown_table(["L", "C", "R"], [], ["left", "center", "right"])
    assert md.splitlines()[1] == "| :--- | :--: | ---: |"


def test_pipes_and_newlines_in_cells_are_escaped():
    md = build_markdown_table(["H"], [["a|b\nc"]])
    assert md.splitlines()[-1] == "| a\\|b c |"


def test_ragged_rows_are_padded_and_extra_cells_dropped():
    assert build_markdown_table(["A", "B", "C"], [["1"]]).splitlines()[-1] == "| 1 |  |  |"
    assert build_markdown_table(["A"], [["1", "2", "3"]]).splitlines()[-1] == "| 1 |"


def test_no_columns_returns_empty():
    assert build_markdown_table([], [["1"]]) == ""


def test_unknown_alignment_falls_back_to_left():
    md = build_markdown_table(["A"], [], ["sideways"])
    assert md.splitlines()[1] == "| :--- |"


def test_header_only_table_has_two_lines():
    assert build_markdown_table(["A", "B"], []).splitlines() == ["| A | B |", "| :--- | :--- |"]
