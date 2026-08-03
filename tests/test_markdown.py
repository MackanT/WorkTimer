"""Tests for src/markdown_utils.py (rendering, sanitization, scoping)."""

from src.markdown_utils import convert_html_to_markdown, render_and_sanitize_markdown


def test_render_is_scoped_under_wt_md():
    """CSS must be scoped so previews don't restyle the whole app (§5)."""
    html = render_and_sanitize_markdown("# Heading")
    assert 'class="wt-md"' in html
    assert ".wt-md h1" in html


def test_checkboxes_get_sequential_ids():
    html = render_and_sanitize_markdown("- [ ] one\n- [x] two")
    assert 'id="notepad-cb-0"' in html
    assert 'id="notepad-cb-1"' in html


def test_data_protocol_is_stripped():
    """data:text/html links are an XSS vector and must not survive (§5)."""
    html = render_and_sanitize_markdown("[x](data:text/html,<script>alert(1)</script>)")
    assert "data:text/html" not in html
    assert "<script>" not in html


def test_empty_input_has_placeholder():
    assert "No content" in render_and_sanitize_markdown("")


def test_convert_html_to_markdown():
    md = convert_html_to_markdown("<h1>Title</h1><p>hello</p>")
    assert "# Title" in md
    assert "hello" in md


def test_convert_strips_scripts():
    md = convert_html_to_markdown("<p>ok</p><script>bad()</script>")
    assert "ok" in md
    assert "bad()" not in md
