"""Import smoke tests — catch breakage in module wiring / page registration."""


def test_main_imports_and_registers_pages():
    """`import main` runs every @ui.page registration without starting the server."""
    import main  # noqa: F401


def test_all_page_modules_import():
    from src.pages import (  # noqa: F401
        open_entity_dialog,
        board_page,
        info_page,
        log_page,
        notepad_page,
        query_editor_page,
        root_page,
        settings_page,
        tasks_page,
        time_tracking_page,
    )


def test_helpers_reexports_are_intact():
    """Modules import these names from helpers; the split must keep them working."""
    from src import helpers

    for name in (
        "UI_STYLES",
        "UIStyles",
        "render_and_sanitize_markdown",
        "convert_html_to_markdown",
        "MARKDOWN_DARK_MODE_CSS",
    ):
        assert hasattr(helpers, name), f"helpers.{name} missing after split"
