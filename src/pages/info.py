"""
Info Page (V2)

Display application information, configuration, and statistics.
Uses V2 architecture with per-client AppCore and event-driven updates.
"""

from nicegui import ui
from ..core.app import AppCore
from ..ui.elements import toolbar, toolbar_group


@ui.page("/info")
async def info_page():
    """Info page - displays application information"""

    # Get or create AppCore for this client
    core = await AppCore.get_or_initialize()

    config_ui = core.ui_config if hasattr(core, "ui_config") else {}

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
                info_icon = (
                    config_ui.get("info", {}).get("meta", {}).get("icon", "person")
                )
                info_label = (
                    config_ui.get("info", {})
                    .get("meta", {})
                    .get("friendly_name", "Info")
                )
                read_me_icon = (
                    config_ui.get("read_me", {}).get("meta", {}).get("icon", "work")
                )
                read_me_label = (
                    config_ui.get("read_me", {})
                    .get("meta", {})
                    .get("friendly_name", "Read Me")
                )
                changelog_icon = (
                    config_ui.get("changelog", {})
                    .get("meta", {})
                    .get("icon", "card_giftcard")
                )
                changelog_label = (
                    config_ui.get("changelog", {})
                    .get("meta", {})
                    .get("friendly_name", "Changelog")
                )
                ui.tab("info", label=info_label, icon=info_icon)
                ui.tab("read_me", label=read_me_label, icon=read_me_icon)
                ui.tab("changelog", label=changelog_label, icon=changelog_icon)

                return main_tabs

    main_tabs = render_toolbar()

    with (
        ui.tab_panels(main_tabs, value="info")
        .props("vertical")
        .classes("w-full")
        .style(
            "background: transparent; height: calc(100vh - 150px); max-height: calc(100vh - 150px);"
        )
    ):
        # Customer tab
        with ui.tab_panel("info"):
            # await render_entity_tabs(
            #     core, "customer", ["add", "update", "disable", "reenable"]
            # )
            print("info", config_ui.get("info", {}))
        # Project tab
        with ui.tab_panel("read_me"):
            # await render_entity_tabs(
            #     core, "project", ["add", "update", "disable", "reenable"]
            # )
            print("read_Me", config_ui.get("read_me", {}))
        # Bonus tab
        with ui.tab_panel("changelog"):
            # await render_entity_tabs(core, "bonus", ["add"])
            print("changelog", config_ui.get("changelog", {}))
