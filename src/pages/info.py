"""
Info Page (V2)

Display application information, configuration, and statistics.
Uses V2 architecture with per-client AppCore and event-driven updates.
"""

from nicegui import ui
from ..core.app import AppCore
from ..ui.elements import toolbar, page_card
from pathlib import Path


async def info_page():
    """Info page - displays application information

    Note: No @ui.page decorator - accessed via SPA sub_pages in root.py
    Direct access to /info is handled by redirect in root.py
    """

    # Get or create AppCore for this client
    core = await AppCore.get_or_initialize()

    info_page_config = core.ui_config.get("info_page", {})

    # ========================================================================
    # Toolbar Controls
    # ========================================================================
    def render_toolbar():
        """Render control panel - stable across data refreshes."""

        with toolbar(core.theme):
            with (
                ui.tabs(value="info")
                .props(
                    f'horizontal dense active-color="{core.theme.get("accent")}" indicator-color="{core.theme.get("accent")}"'
                )
                .classes("text-xs text-white uppercase tracking-wide whitespace-nowrap")
            ) as main_tabs:
                for page_dict in info_page_config:
                    p_data = info_page_config.get(page_dict, {}).get("meta", {})
                    icon = p_data.get("icon", "warning")
                    label = p_data.get("friendly_name", page_dict)
                    ui.tab(page_dict, label=label, icon=icon)
                return main_tabs

    main_tabs = render_toolbar()

    def render_info_text(markdown_file: str):
        with page_card():
            try:
                content = (
                    Path(__file__).parent.parent.parent / "docs" / markdown_file
                ).read_text(encoding="utf-8")
            except Exception as e:
                content = f"Error loading content: {e}"
            ui.markdown(content=content)

    start_tab = next(iter(info_page_config))

    with (
        ui.tab_panels(main_tabs, value=start_tab)
        .props("vertical")
        .classes("w-full")
        .style(
            "background: transparent; height: calc(100vh - 156px); max-height: calc(100vh - 156px);"
        )
    ):
        for page_dict in info_page_config:
            p_data = info_page_config.get(page_dict, {}).get("meta", {})
            filename = p_data.get("file", f"{page_dict}.md")
            with ui.tab_panel(page_dict).classes("p-0"):
                render_info_text(filename)
