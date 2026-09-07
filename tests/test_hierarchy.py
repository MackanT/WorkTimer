"""Tests for the DevOps hierarchy Mermaid builder (src/pages/hierarchy.py)."""

import numpy as np
import pandas as pd

from src.pages.hierarchy import (
    _descendants,
    _sanitize_label,
    build_mermaid,
    default_focus_id,
    focus_options,
)


def _df(rows):
    return pd.DataFrame(rows)


def _two_epic_tree():
    return _df([
        {"customer_name": "A", "type": "Epic", "id": 1, "title": "E1", "state": "Active", "parent_id": None},
        {"customer_name": "A", "type": "Feature", "id": 2, "title": "F", "state": "Active", "parent_id": 1},
        {"customer_name": "A", "type": "User Story", "id": 3, "title": "US", "state": "New", "parent_id": 2},
        {"customer_name": "A", "type": "Epic", "id": 10, "title": "E2", "state": "Active", "parent_id": None},
        {"customer_name": "A", "type": "Feature", "id": 11, "title": "F2", "state": "Active", "parent_id": 10},
    ])


def test_builds_nodes_edges_and_column_classes():
    df = _df([
        {"customer_name": "A", "type": "Epic", "id": 1, "title": "E", "state": "Active", "parent_id": None, "board_column": "Doing"},
        {"customer_name": "A", "type": "Feature", "id": 2, "title": "F", "state": "Active", "parent_id": 1, "board_column": "On Hold"},
        {"customer_name": "A", "type": "User Story", "id": 3, "title": "US", "state": "New", "parent_id": 2, "board_column": None},
    ])
    code = build_mermaid(df, "A")

    assert code.startswith("flowchart TD")
    # Epic/Feature labels may carry a progress rollup suffix, so match loosely.
    assert "#1: E" in code
    assert "#2: F" in code
    assert 'n3("#3: US")' in code
    assert "n1 --> n2" in code
    assert "n2 --> n3" in code
    # Nodes are coloured by board column (sorted case-insensitively:
    # "Doing" -> bc0, "On Hold" -> bc1); no column -> the neutral class.
    assert "class n1 bc0;" in code
    assert "class n2 bc1;" in code
    assert "class n3 nocol;" in code
    assert "classDef bc0" in code
    assert "classDef bc1" in code
    assert "classDef nocol" in code


def test_done_column_items_grey_out():
    # A done-token board column greys the node even while its state is Active.
    df = _df([
        {"customer_name": "A", "type": "User Story", "id": 5, "title": "X", "state": "Active", "parent_id": None, "board_column": "Done"},
    ])
    code = build_mermaid(df, "A")
    assert "class n5 done;" in code
    assert "classDef done" in code


def test_closed_items_hidden_by_default():
    df = _df([
        {"customer_name": "A", "type": "Epic", "id": 1, "title": "E", "state": "Active", "parent_id": None},
        {"customer_name": "A", "type": "Feature", "id": 2, "title": "F", "state": "Closed", "parent_id": 1},
    ])
    assert "n2" not in build_mermaid(df, "A")

    with_closed = build_mermaid(df, "A", include_closed=True)
    assert "n2" in with_closed
    assert "n1 --> n2" in with_closed


def test_item_with_hidden_parent_becomes_root():
    # Story's parent Feature is Closed (filtered) -> story renders with no edge.
    df = _df([
        {"customer_name": "A", "type": "Feature", "id": 2, "title": "F", "state": "Closed", "parent_id": None},
        {"customer_name": "A", "type": "User Story", "id": 3, "title": "US", "state": "New", "parent_id": 2},
    ])
    code = build_mermaid(df, "A")
    assert "n3" in code
    assert "n2" not in code
    assert "-->" not in code


def test_nan_parent_is_a_root():
    df = _df([
        {"customer_name": "A", "type": "Epic", "id": 1, "title": "E", "state": "Active", "parent_id": np.nan},
    ])
    code = build_mermaid(df, "A")
    assert "n1" in code
    assert "-->" not in code


def test_empty_cases_return_blank():
    df = _df([
        {"customer_name": "A", "type": "Epic", "id": 1, "title": "E", "state": "Active", "parent_id": None},
    ])
    assert build_mermaid(df, "B") == ""  # unknown customer
    assert build_mermaid(df, None) == ""
    assert build_mermaid(pd.DataFrame(), "A") == ""


def test_label_sanitization_and_truncation():
    assert '"' not in _sanitize_label('a "quoted" b')
    assert "<" not in _sanitize_label("a <tag> b")
    assert ">" not in _sanitize_label("a <tag> b")
    assert len(_sanitize_label("x" * 100)) <= 42


def test_label_strips_metadata_tags_and_delimiters():
    # Real epic titles look like "Navigator [ref:X | kst:100407 pnr:1007355]".
    out = _sanitize_label("Navigator [ref:Johan | kst:100407]")
    assert out == "Navigator"  # the whole [ ... ] tag is dropped


def test_label_whitelist_leaves_only_safe_chars():
    import re as _re

    out = _sanitize_label("A/B + C 5%? (x) [y] {z} <w> |v| #h; d")
    assert _re.search(r"[^\w\s.,:\-]", out) is None  # nothing unsafe survives


def test_label_keeps_nordic_letters_and_dashes():
    assert _sanitize_label("Förvaltning å ä ö - test") == "Förvaltning å ä ö - test"


def test_real_world_title_produces_readable_label():
    df = _df([
        {"customer_name": "A", "type": "Epic", "id": 9, "title": "Navigator [ref:X | kst:100]", "state": "Active", "parent_id": None},
    ])
    code = build_mermaid(df, "A")
    # The node carries clean text, no bracket-family delimiter leaked.
    assert 'n9("#9: Navigator")' in code


def test_direction_prefix():
    df = _two_epic_tree()
    assert build_mermaid(df, "A").startswith("flowchart TD")
    assert build_mermaid(df, "A", direction="LR").startswith("flowchart LR")


def test_descendants_collects_transitive_children():
    keep = _descendants(_two_epic_tree(), 1)
    assert keep == {1, 2, 3}


def test_focus_on_epic_shows_only_its_subtree():
    code = build_mermaid(_two_epic_tree(), "A", focus_id=1)
    for node in ("n1", "n2", "n3"):
        assert f"{node}(" in code
    assert "n10(" not in code
    assert "n11(" not in code


def test_focus_on_feature_shows_feature_and_below():
    code = build_mermaid(_two_epic_tree(), "A", focus_id=2)
    assert "n2(" in code and "n3(" in code
    assert "n1(" not in code and "n10(" not in code


def test_progress_rollup_on_parents_counts_all_states():
    rows = [
        {"customer_name": "A", "type": "Epic", "id": 1, "title": "E", "state": "Active", "parent_id": None},
        {"customer_name": "A", "type": "Feature", "id": 2, "title": "F", "state": "Active", "parent_id": 1},
        {"customer_name": "A", "type": "User Story", "id": 3, "title": "S1", "state": "Closed", "parent_id": 2},
        {"customer_name": "A", "type": "User Story", "id": 4, "title": "S2", "state": "Resolved", "parent_id": 2},
        {"customer_name": "A", "type": "User Story", "id": 5, "title": "S3", "state": "Active", "parent_id": 2},
    ]
    code = build_mermaid(_df(rows), "A", include_closed=True)
    # Epic and Feature both roll up 2 done of 3 stories (Closed + Resolved = done).
    assert 'n1("#1: E  2 of 3 done")' in code
    assert 'n2("#2: F  2 of 3 done")' in code


def test_done_items_get_the_done_class():
    rows = [
        {"customer_name": "A", "type": "User Story", "id": 9, "title": "S", "state": "Resolved", "parent_id": None},
    ]
    code = build_mermaid(_df(rows), "A")
    assert "classDef done" in code
    assert "class n9 done;" in code
    assert "class n9 story;" not in code


def test_default_focus_small_tree_is_whole():
    # 5 nodes, well under the threshold -> open whole (None).
    assert default_focus_id(_two_epic_tree(), "A", threshold=60) is None


def test_default_focus_large_tree_picks_first_epic():
    rows = [
        {"customer_name": "A", "type": "Epic", "id": 1, "title": "E1", "state": "Active", "parent_id": None},
        {"customer_name": "A", "type": "Epic", "id": 2, "title": "E2", "state": "Active", "parent_id": None},
    ]
    # pad with many user stories so the tree exceeds the threshold
    rows += [
        {"customer_name": "A", "type": "User Story", "id": 100 + i, "title": f"US{i}",
         "state": "Active", "parent_id": 1}
        for i in range(10)
    ]
    assert default_focus_id(_df(rows), "A", threshold=5) == 1  # first (lowest-id) Epic


def test_focus_options_lists_epics_and_features_only():
    opts = focus_options(_two_epic_tree(), "A")
    assert opts[""] == "Whole tree"
    assert set(opts) == {"", "1", "2", "10", "11"}  # no user story (id 3)
    # Epics are listed before Features.
    keys = [k for k in opts if k]
    assert keys.index("1") < keys.index("2")
