"""Tests for the markdown-table builder + parser (src/ui/dynamic_widgets)."""

from src.ui.dynamic_widgets import build_markdown_table, parse_markdown_table


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


# --- parse_markdown_table ---------------------------------------------------


def test_parse_basic_table_and_alignments():
    headers, rows, aligns = parse_markdown_table(
        "| A | B | C |\n| :--- | :--: | ---: |\n| 1 | 2 | 3 |"
    )
    assert headers == ["A", "B", "C"]
    assert rows == [["1", "2", "3"]]
    assert aligns == ["left", "center", "right"]


def test_parse_rejects_non_tables():
    assert parse_markdown_table("just some text") is None
    assert parse_markdown_table("| A | B |") is None  # no separator row
    assert parse_markdown_table("") is None


def test_parse_pads_and_truncates_rows_to_header_count():
    _, rows, _ = parse_markdown_table("| A | B | C |\n| - | - | - |\n| 1 |\n| 1 | 2 | 3 | 4 |")
    assert rows == [["1", "", ""], ["1", "2", "3"]]


def test_parse_unescapes_pipes():
    _, rows, _ = parse_markdown_table("| H |\n| --- |\n| a\\|b |")
    assert rows == [["a|b"]]


def test_build_then_parse_roundtrip():
    md = build_markdown_table(
        ["Name", "Qty", "Price"], [["Apple", "3", "12"]], ["left", "center", "right"]
    )
    headers, rows, aligns = parse_markdown_table(md)
    assert headers == ["Name", "Qty", "Price"]
    assert rows == [["Apple", "3", "12"]]
    assert aligns == ["left", "center", "right"]
