"""Description templates: the override merge (config/description_templates.yml
→ the add form's description_editor field) and the {{placeholder}} machinery
behind template fill + dropdown line sync."""

from datetime import date

from src.config import merge_description_templates
from src.helpers import (
    fill_template,
    sync_template_text,
    template_has_field,
)


def _ui_yaml(tpl):
    return {
        "board_devops_forms": {
            "add": {
                "fields": [
                    {"name": "work_item_title"},
                    {"name": "description_editor", "templates": dict(tpl)},
                ]
            }
        }
    }


def test_merge_overrides_and_adds_levels():
    ui = _ui_yaml({"Epic": "E", "Feature": "F"})
    merge_description_templates(ui, {"Epic": "NEW", "Sub-task": "S", "bad": 42})
    tpl = ui["board_devops_forms"]["add"]["fields"][1]["templates"]
    assert tpl == {"Epic": "NEW", "Feature": "F", "Sub-task": "S"}


def test_merge_tolerates_missing_field_or_sections():
    merge_description_templates({"board_devops_forms": {"add": {"fields": [{"name": "x"}]}}}, {"Epic": "E"})
    merge_description_templates({}, {"Epic": "E"})  # no crash either


def test_merge_empty_overrides_is_a_noop():
    ui = _ui_yaml({"Epic": "E"})
    merge_description_templates(ui, {})
    merge_description_templates(ui, None)
    assert ui["board_devops_forms"]["add"]["fields"][1]["templates"] == {"Epic": "E"}


# ── {{placeholder}} machinery ────────────────────────────────────────────────


def test_fill_template_double_and_legacy_braces():
    out = fill_template(
        "Date: {{today}} / {today}\nSrc: {{source}}\nOld: {source}",
        {"source": "Email"},
    )
    today = str(date.today())
    assert out == f"Date: {today} / {today}\nSrc: Email\nOld: Email"


def test_fill_template_alias_none_and_unknown():
    out = fill_template(
        "C: {{contact}}\nX: {{no_such_field}}", {"contact_person": None}
    )
    # Alias resolves; None renders empty; unknown stays literal (visible typo).
    assert out == "C: \nX: {{no_such_field}}"


def test_template_has_field_sees_aliases():
    assert template_has_field("x {{contact}} y", "contact_person")
    assert template_has_field("x {{source}}", "source")
    assert not template_has_field("x {{source}}", "contact_person")
    assert not template_has_field("no placeholders", "source")


# The exact template that broke the first (prefix/suffix) implementation:
# two placeholders on one line, an alias, and the same field on two lines.
_CRAZY = (
    "**Received Date:** {{today}}\n"
    "**Source:** HALLA {{source}} arst ntr {{contact}}\n"
    "**Contact:** {{contact_person}}\n"
    "\n"
    "## Problem\n"
)


def test_sync_template_text_multi_placeholder_lines_and_aliases():
    # As rendered at dialog-open with both dropdowns empty:
    text = fill_template(_CRAZY, {"source": "", "contact_person": ""})
    assert "**Source:** HALLA  arst ntr " in text

    # User picks a source → the multi-placeholder line re-renders.
    text = sync_template_text(text, _CRAZY, {"source": "Email", "contact_person": ""})
    assert "**Source:** HALLA Email arst ntr " in text

    # Then picks a contact → BOTH its lines update (alias + full name),
    # and the source value survives.
    text = sync_template_text(
        text, _CRAZY, {"source": "Email", "contact_person": "Jane"}
    )
    assert "**Source:** HALLA Email arst ntr Jane" in text
    assert "**Contact:** Jane" in text
    assert "## Problem" in text


def test_sync_template_text_moved_and_relabelled_line():
    raw = "# Head\n**Ursprung:** {{source}} (given)\nBody"
    text = fill_template(raw, {"source": "Teams"})
    out = sync_template_text(text, raw, {"source": "Email"})
    assert out == "# Head\n**Ursprung:** Email (given)\nBody"


def test_sync_template_text_skips_unanchorable_and_missing_lines():
    # A line that is ONLY a placeholder can't be located again → skipped.
    raw = "{{source}}\n**Src:** {{source}}"
    text = fill_template(raw, {"source": "A"})
    out = sync_template_text(text, raw, {"source": "B"})
    assert out == "A\n**Src:** B"
    # A template line the user deleted from the text → left alone.
    out2 = sync_template_text("only this line", raw, {"source": "C"})
    assert out2 == "only this line"
