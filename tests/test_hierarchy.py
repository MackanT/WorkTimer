"""Tests for the DevOps hierarchy Mermaid builder (src/pages/hierarchy.py)."""

import numpy as np
import pandas as pd

from src.pages.hierarchy import _sanitize_label, build_mermaid


def _df(rows):
    return pd.DataFrame(rows)


def test_builds_nodes_edges_and_type_classes():
    df = _df([
        {"customer_name": "A", "type": "Epic", "id": 1, "title": "E", "state": "Active", "parent_id": None},
        {"customer_name": "A", "type": "Feature", "id": 2, "title": "F", "state": "Active", "parent_id": 1},
        {"customer_name": "A", "type": "User Story", "id": 3, "title": "US", "state": "New", "parent_id": 2},
    ])
    code = build_mermaid(df, "A")

    assert code.startswith("flowchart TD")
    assert 'n1["#1: E"]' in code
    assert 'n2["#2: F"]' in code
    assert 'n3["#3: US"]' in code
    assert "n1 --> n2" in code
    assert "n2 --> n3" in code
    assert "class n1 epic;" in code
    assert "class n2 feature;" in code
    assert "class n3 story;" in code
    assert "classDef epic" in code


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
