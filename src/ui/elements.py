"""
Generalized UI Components used throughout the application.
"""

import asyncio

from nicegui import ui, app
from contextlib import contextmanager
from ..helpers import UI_STYLES


class NavigationBar:
    """
    Provides a consistent top banner navigation for all pages.
    Manages navigation bar state and rendering
    """

    def __init__(self, theme: dict, navigation_config: dict):
        self.theme = theme
        self.navigation_config = navigation_config
        self.buttons = {}
        self.active_path = None
        self.on_navigate = None
        self._active_timers_row = None

    def render(self) -> None:
        """
        Create the top navigation banner with buttons to all main areas.
        Uses app.storage.client to ensure navigation is only created once per client session.
        """
        try:
            if app.storage.client.get("navigation_created", False):
                return
            app.storage.client["navigation_created"] = True
            
            nav_config = self.navigation_config
            
            nav_items = []
            for row in nav_config.values():
                if row.get("enabled", True):
                    nav_items.append(row)

            nav_text = self.theme.get("muted")
            nav_hover = self.theme.get("toolbar_bg")

            # Create header-like navigation bar using regular elements
            with (
                ui.header()
                .classes("items-center")
                .style(
                    f"background-color: {self.theme.get('dark_page', '#0f172a')} !important;"
                    "overflow: hidden !important;"
                )
                .props("flat")
            ):
                with ui.row().classes("items-center gap-1 flex-nowrap overflow-x-auto w-full wt-nav-scroll py-1").style(
                    "scrollbar-width: none;"  # hide scrollbar (Firefox)
                    "-ms-overflow-style: none;"  # hide scrollbar (IE/Edge)
                ):
                    ui.label("WorkTimer").classes("text-h6 text-white font-bold mr-4 shrink-0")

                    # Navigation buttons
                    for item in nav_items:

                        def create_click_handler(path):
                            def handler():
                                self.set_active(path, self.theme)
                                if self.on_navigate:
                                    asyncio.create_task(self.on_navigate())
                                ui.navigate.to(path)

                            return handler

                        button = ui.button(
                            item["label"],
                            icon=item["icon"],
                            on_click=create_click_handler(item["path"]),
                        ).props("flat")

                        button.classes(f"text-{nav_text} hover:bg-{nav_hover} shrink-0")

                        # Store button reference
                        self.buttons[item["path"]] = button

                    # Active timers section — right side of nav bar
                    ui.space()
                    self._active_timers_row = (
                        ui.row().classes("items-center gap-1 mr-2 shrink-0")
                    )

            # Set initial active state based on current path
            current_path = app.storage.client.get("current_path", "/time")
            self.set_active(current_path, self.theme)

        except Exception as e:
            print(f"[Navigation] ERROR creating navigation: {e}")
            import traceback

            traceback.print_exc()

    def set_active_timers(self, names: list[str]) -> None:
        """Update the nav bar active timer pills and the Time button icon/glow."""
        btn = self.buttons.get("/time")
        active = bool(names)

        if btn:
            if active:
                btn.props("icon=timer")
                btn.style(
                    f"box-shadow: 0 0 0 2px {self.theme.get('info')}; border-radius: 4px;"
                )
            else:
                btn.props("icon=schedule")
                btn.style("box-shadow: none;")

        if self._active_timers_row is None:
            return
        self._active_timers_row.clear()
        if not active:
            return
        with self._active_timers_row:
            ui.icon("timer", size="xs").classes("text-green-400 shrink-0")
            for name in names:
                (
                    ui.label(name)
                    .classes(
                        "text-xs text-green-300 border border-green-600"
                        " px-2 py-0.5 rounded-full whitespace-nowrap"
                    )
                )

    def set_timer_active(self, active: bool, tooltip_lines: list[str] | None = None):
        """Legacy shim — delegates to set_active_timers."""
        self.set_active_timers(tooltip_lines or [] if active else [])

    def set_active(self, path: str, theme: dict):
        """Update the active navigation button"""
        self.active_path = path
        nav_active = theme.get("accent")
        nav_text = theme.get("muted")
        nav_hover = theme.get("toolbar_bg")

        for btn_path, btn in self.buttons.items():
            # Remove all potential classes
            btn.classes(
                remove=f"bg-{nav_active} text-white text-{nav_text} hover:bg-{nav_hover}"
            )

            # Apply correct classes
            if btn_path == path:
                btn.classes(add=f"bg-{nav_active} text-white")
            else:
                btn.classes(add=f"text-{nav_text} hover:bg-{nav_hover}")


def toolbar_divider(theme):
    ui.element("div").classes(f"h-6 w-px shrink-0 bg-{theme.get('divider')}")


# Height constants kept for backward compat (not used for layout calculations).
TOOLBAR_HEIGHT_PX = 56

# Kept so existing imports don't break — not used for layout anymore.
NAV_HEIGHT_PX = 50
PAGE_HEIGHT = "var(--wt-page-h)"   # legacy; prefer the flex model
INNER_HEIGHT = "var(--wt-inner-h)" # legacy; prefer the flex model


@contextmanager
def toolbar(theme):
    """Toolbar component - fixed height, shrinks to its natural size in flex column."""
    with (
        ui.row()
        .classes(
            f"wt-toolbar wt-toolbar-scroll w-full shrink-0 items-center gap-6 px-6 bg-{theme.get('toolbar_bg')} rounded-md flex-nowrap overflow-x-auto"
        )
        .style(
            f"height: {TOOLBAR_HEIGHT_PX}px; min-height: {TOOLBAR_HEIGHT_PX}px; max-height: {TOOLBAR_HEIGHT_PX}px; box-sizing: border-box;"
            " scrollbar-width: none; -ms-overflow-style: none;"
        )
    ):
        yield


@contextmanager
def toolbar_group(theme, label: str | None = None, divider_after: bool = True):
    with ui.element("div").classes("flex shrink-0 items-center gap-2"):
        if label is not None:
            ui.label(label).classes(
                f"text-xs text-{theme.get('accent')} uppercase tracking-wide whitespace-nowrap"
            )
        yield
    if divider_after:
        toolbar_divider(theme)


@contextmanager
def entity_card_shell(constrain_width: bool = True):
    """Top level card shell for entity cards (customers/projects).

    Fills the available height of its flex-row parent.

    Args:
        constrain_width: If True, applies max-width constraint (for time_tracking cards).
                        If False, uses full width (for task forms in splitter panel).
    """

    base_classes = "w-full mx-auto mb-2 p-4"

    with (
        ui.card()
        .classes(f"{base_classes} rounded-md")
        .style(
            "display:flex; flex-direction:column; height:100%; min-width:280px; box-sizing:border-box;"
        )
        .props("flat")
    ):
        # Apply width constraints only when needed (time_tracking page)
        if constrain_width:
            column_style = UI_STYLES.get_inline_style("time_tracking", "customer_card")
            column_classes = f"{UI_STYLES.get_layout_classes('time_tracking_customer_column')} flex-1 min-h-0"
        else:
            # Full width mode: stretch children to fill available width
            column_style = "width: 100%; align-items: stretch;"
            column_classes = "flex-1 min-h-0 w-full"

        with ui.column().classes(column_classes).style(column_style):
            yield


@contextmanager
def entity_card_header():
    """Header row with left/right slots"""
    with (
        ui.row()
        .classes(UI_STYLES.get_layout_classes("time_tracking_customer_header"))
        .style(UI_STYLES.get_inline_style("time_tracking", "customer_header"))
        .classes("justify-between")
    ):
        yield


@contextmanager
def entity_card_content():
    """Scrollable content area"""
    with (
        ui.element()
        .classes("w-full overflow-auto flex-1 min-h-0")
        .style("padding-right: 1rem; scrollbar-gutter: stable;")
    ):
        yield


@contextmanager
def page_card(scrollable: bool = True):
    """Full-height main page card.

    Fills the remaining vertical space in the page's flex column via the
    .wt-page-content class (defined in main.py global CSS).

    Args:
        scrollable: Whether to enable vertical scrolling (default: True).
                    Non-scrollable cards use an inner flex column so children
                    can in turn use flex-fill to take remaining space.
    """
    overflow_style = "overflow-y: auto;" if scrollable else "overflow-y: hidden;"
    inner_flex = "" if scrollable else "display: flex; flex-direction: column;"

    with (
        ui.card()
        .classes("wt-page-content mx-4 my-2 rounded-md flex flex-col")
        .style(f"width: calc(100% - 2rem); box-sizing: border-box; {overflow_style} {inner_flex}")
        .props("flat")
    ):
        yield
