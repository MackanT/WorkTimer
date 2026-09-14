"""
Markdown & HTML rendering utilities.

Markdown → sanitized dark-mode HTML (notepad, DevOps descriptions) and
HTML → markdown conversion (importing ADO descriptions). Split out of
helpers.py (which re-exports these names for backward compatibility —
config `render_function:` lookups resolve through helpers).
"""

import html as _html
import re
from urllib.parse import quote as _urlquote

import bleach as _bleach
import markdown as _markdown
from markdownify import markdownify as _markdownify
from pygments.formatters import HtmlFormatter as _HtmlFormatter

# Pygments monokai CSS injected alongside MARKDOWN_DARK_MODE_CSS (class-based, no bleach interaction)
_PYGMENTS_MONOKAI_CSS = _HtmlFormatter(style="monokai").get_style_defs(".wt-md .highlight")

# Dark mode CSS for markdown rendering.
# Every rule is scoped under .wt-md — CSS in a <style> tag is document-global,
# so unscoped element selectors (h1, p, code, …) would restyle the whole app
# whenever a preview is on screen.
MARKDOWN_DARK_MODE_CSS = """
<style>
    .wt-md h1 { font-size: 2em; font-weight: bold; margin: 0.67em 0; border-bottom: 2px solid #555; padding-bottom: 0.3em; color: #ffffff; }
    .wt-md h2 { font-size: 1.5em; font-weight: bold; margin: 0.75em 0; border-bottom: 1px solid #555; padding-bottom: 0.3em; color: #f0f0f0; }
    .wt-md h3 { font-size: 1.25em; font-weight: bold; margin: 0.83em 0; color: #f0f0f0; }
    .wt-md h4 { font-size: 1.1em; font-weight: bold; margin: 1em 0; color: #e8e8e8; }
    .wt-md h5 { font-size: 1em; font-weight: bold; margin: 1.17em 0; color: #e8e8e8; }
    .wt-md h6 { font-size: 0.9em; font-weight: bold; margin: 1.33em 0; color: #aaa; }
    .wt-md ul, .wt-md ol { margin: 1em 0; padding-left: 2em; color: #e0e0e0; }
    .wt-md ul { list-style-type: disc; }
    .wt-md ol { list-style-type: decimal; }
    .wt-md li { margin: 0.25em 0; }
    .wt-md p { margin: 1em 0; color: #e0e0e0; }
    .wt-md blockquote { border-left: 4px solid #666; padding-left: 1em; margin: 1em 0; color: #aaa; font-style: italic; }
    .wt-md code { background-color: #2d2d2d; color: #f8f8f2; padding: 2px 6px; border-radius: 3px; font-family: 'Courier New', monospace; font-size: 0.9em; }
    .wt-md pre { background-color: #2d2d2d; padding: 16px; border-radius: 6px; overflow-x: auto; border: 1px solid #444; }
    .wt-md pre code { background-color: transparent; padding: 0; }
    /* Let Pygments control highlighted block styling */
    .wt-md div.highlight { border-radius: 6px; overflow: hidden; margin: 1em 0; }
    .wt-md div.highlight pre { background-color: transparent; border: none; margin: 0; }
    .wt-md table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    .wt-md th, .wt-md td { border: 1px solid #555; padding: 8px; text-align: left; color: #e0e0e0; }
    .wt-md th { background-color: #2d2d2d; font-weight: bold; }
    .wt-md strong { font-weight: bold; color: #ffffff; }
    .wt-md em { font-style: italic; }
    .wt-md hr { border: none; border-top: 2px solid #555; margin: 2em 0; }
    .wt-md a { color: #64b5f6; text-decoration: none; }
    .wt-md a:hover { text-decoration: underline; }
    .wt-md ul.contains-task-list { list-style: none; padding-left: 1.5em; }
    .wt-md .task-list-item { list-style: none; padding-left: 0; }
    .wt-md .task-list-item input[type="checkbox"] { margin-right: 0.5em; cursor: pointer; accent-color: #64b5f6; vertical-align: middle; width: 1em; height: 1em; }
</style>
"""


def render_and_sanitize_markdown(text: str) -> str:
    """Convert markdown to sanitized HTML with dark mode styling.

    Args:
        text: Markdown text to render

    Returns:
        Sanitized HTML string with inline CSS for dark mode
    """
    if not text:
        return "<p style='color: #999;'>No content to preview</p>"

    # Render markdown with proper extensions
    raw_html = _markdown.markdown(
        text,
        extensions=[
            # Individual sub-extensions from 'extra' — excluding fenced_code
            # so pymdownx.superfences can own fenced code block parsing.
            "abbr",
            "attr_list",
            "def_list",
            "footnotes",
            "tables",
            "md_in_html",
            "nl2br",
            "sane_lists",
            "pymdownx.tilde",
            "pymdownx.tasklist",
            "pymdownx.highlight",
            "pymdownx.superfences",
        ],
        extension_configs={
            "pymdownx.highlight": {
                "use_pygments": True,
                "pygments_style": "monokai",
            },
            "pymdownx.tilde": {
                "subscript": False,
            },
            "pymdownx.tasklist": {
                "custom_checkbox": False,
                "clickable_checkbox": True,
            },
        },
    )

    allowed_tags = list(_bleach.sanitizer.ALLOWED_TAGS) + [
        "p",
        "pre",
        "code",
        "div",
        "span",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "img",
        "br",
        "hr",
        "input",
        "ul",
        "ol",
        "li",
        "blockquote",
        "strong",
        "em",
        "del",
        "s",
        "ins",
    ]
    allowed_attrs = {
        "a": ["href", "title", "target"],
        "img": ["src", "alt", "width", "height"],
        "input": ["type", "checked", "disabled", "id"],
        "code": ["class"],
        "pre": ["class"],
        "span": ["class"],
        "div": ["class"],
        "*": ["class"],
    }

    # Note: no "data:" protocol — data:text/html links are an XSS vector.
    # Pasted images use relative /notes_assets/ paths, so nothing needs it.
    cleaned_html = _bleach.clean(
        raw_html,
        tags=allowed_tags,
        attributes=allowed_attrs,
        protocols=["http", "https", "mailto"],
        strip=True,
    )

    # Post-process: stamp each checkbox with a sequential id so JS can
    # report which one was clicked back to Python.
    # bleach/html5lib reorders attributes alphabetically, so the regex must
    # match <input ...> tags that contain type="checkbox" anywhere.
    _cbidx = [0]

    def _stamp_cbidx(m: re.Match) -> str:
        tag = m.group(0)
        idx = _cbidx[0]
        _cbidx[0] += 1
        # Handle both '>' and self-closing '/>' endings
        closing = "/>" if tag.endswith("/>") else ">"
        return f'{tag[: -len(closing)]} id="notepad-cb-{idx}"{closing}'

    cleaned_html = re.sub(r'<input\b[^>]*\btype="checkbox"[^>]*>', _stamp_cbidx, cleaned_html)

    # DevOps work-item attachments (dev.azure.com/.../_apis/wit/attachments/…)
    # need a PAT the browser doesn't have, so route <img> srcs through our
    # authenticated proxy for the preview only. The stored markdown keeps the
    # real DevOps URL, so it still renders inside Azure DevOps.
    def _proxy_devops_attachment(m: re.Match) -> str:
        return m.group(1) + "/devops_attachment?url=" + _urlquote(m.group(2), safe="") + m.group(3)

    cleaned_html = re.sub(
        r'(<img\b[^>]*\bsrc=")'
        r'(https://[^"]*(?:/_apis/wit/attachments/|/rest/api/3/attachment/)[^"]*)'
        r'(")',
        _proxy_devops_attachment,
        cleaned_html,
    )

    # Return with dark mode styling (scoped under .wt-md, see MARKDOWN_DARK_MODE_CSS)
    return f"""
    <div class="wt-md" style="font-family: system-ui, -apple-system, sans-serif; line-height: 1.6; color: #e0e0e0;">
        {MARKDOWN_DARK_MODE_CSS}
        <style>{_PYGMENTS_MONOKAI_CSS}</style>
        {cleaned_html}
    </div>
    """


def convert_html_to_markdown(html_text: str) -> str:
    """Convert HTML content to clean markdown text.

    Args:
        html_text: HTML content to convert

    Returns:
        Clean markdown text suitable for editing
    """
    if not html_text or not html_text.strip():
        return ""

    # Pre-process to remove script and style tags
    html_text = re.sub(
        r"<script[^>]*>.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE
    )
    html_text = re.sub(
        r"<style[^>]*>.*?</style>", "", html_text, flags=re.DOTALL | re.IGNORECASE
    )

    # Use markdownify to convert HTML to markdown
    markdown_text = _markdownify(
        html_text,
        heading_style="atx",  # Use # style headers
        bullets="-",  # Use - for bullet points
        autolinks=False,  # Don't auto-convert URLs
        default_title=True,  # Include title attributes
    ).strip()

    # Clean up common HTML artifacts
    markdown_text = _html.unescape(markdown_text)

    # Clean up excessive whitespace and normalize line breaks
    cleaned_lines = [line.rstrip() for line in markdown_text.split("\n")]
    result = "\n".join(cleaned_lines)

    # Replace multiple consecutive blank lines with just two
    result = re.sub(r"\n\n\n+", "\n\n", result)

    return result.strip()
