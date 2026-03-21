"""
Generalized UI Components used throughout the application.
"""

from nicegui import ui, app
from contextlib import contextmanager
from ..helpers import UI_STYLES


class NavigationBar:
    """
    Provides a consistent top banner navigation for all pages.
    Manages navigation bar state and rendering
    """

    def __init__(self, theme: dict):
        self.theme = theme
        self.buttons = {}
        self.active_path = None

    def render(self) -> None:
        """
        Create the top navigation banner with buttons to all main areas.
        Uses app.storage.client to ensure navigation is only created once per client session.
        """
        try:
            if app.storage.client.get("navigation_created", False):
                return
            app.storage.client["navigation_created"] = True

            nav_items = [
                {
                    "label": "Time Tracking",
                    "icon": "schedule",
                    "path": "/time",
                    "key": "time_tracking",
                },
                {
                    "label": "Data Input",
                    "icon": "input",
                    "path": "/add_data",
                    "key": "add_data",
                },
                {
                    "label": "Query Editor",
                    "icon": "code",
                    "path": "/query_editor",
                    "key": "query_editor",
                },
                {
                    "label": "Tasks",
                    "icon": "check_box",
                    "path": "/tasks",
                    "key": "tasks",
                },
                {"label": "Log", "icon": "terminal", "path": "/log", "key": "log"},
                {"label": "Info", "icon": "info", "path": "/info", "key": "info"},
            ]

            nav_text = self.theme.get("muted")
            nav_hover = self.theme.get("toolbar_bg")

            # Create header-like navigation bar using regular elements
            with (
                ui.header()
                .classes(f"items-center justify-between bg-{self.theme.get('nav_bg')}")
                .props("flat")
            ):
                with ui.row().classes("items-center gap-1"):
                    ui.label("WorkTimer").classes("text-h6 text-white font-bold mr-4")

                    # Navigation buttons
                    for item in nav_items:

                        def create_click_handler(path):
                            def handler():
                                self.set_active(path, self.theme)
                                ui.navigate.to(path)

                            return handler

                        button = ui.button(
                            item["label"],
                            icon=item["icon"],
                            on_click=create_click_handler(item["path"]),
                        ).props("flat")

                        button.classes(f"text-{nav_text} hover:bg-{nav_hover}")

                        # Store button reference
                        self.buttons[item["path"]] = button

            # Set initial active state based on current path
            current_path = app.storage.client.get("current_path", "/time")
            self.set_active(current_path, self.theme)

        except Exception as e:
            print(f"[Navigation] ERROR creating navigation: {e}")
            import traceback

            traceback.print_exc()

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
    ui.element("div").classes(f"h-6 w-px bg-{theme.get('divider')}")


@contextmanager
def toolbar(theme):
    """Toolbar component - consistent height and styling across all pages"""
    with (
        ui.row()
        .classes(
            f"w-full items-center gap-6 px-6 bg-{theme.get('toolbar_bg')} rounded-md"
        )
        .style(
            "height: 56px; min-height: 56px; max-height: 56px; box-sizing: border-box;"
        )
    ):
        yield


@contextmanager
def toolbar_group(theme, label: str, divider_after: bool = True):
    with ui.element("div").classes("flex items-center gap-2"):
        ui.label(label).classes(
            f"text-xs text-{theme.get('accent')} uppercase tracking-wide whitespace-nowrap"
        )
        yield
    if divider_after:
        toolbar_divider(theme)


@contextmanager
def entity_card_shell(constrain_width: bool = True):
    """Top level card shell for entity cards (customers/projects)

    Args:
        constrain_width: If True, applies max-width constraint (for time_tracking cards).
                        If False, uses full width (for task forms in splitter panel).
    """

    base_classes = "w-full mx-auto mb-2 p-4"

    with (
        ui.card()
        .classes(f"{base_classes} rounded-md")
        .style(
            "display:flex; flex-direction:column; height:calc(100vh - 220px); min-width:280px; box-sizing:border-box;"
        )
        .props("flat")
    ):
        # Apply width constraints only when needed (time_tracking page)
        column_style = (
            UI_STYLES.get_inline_style("time_tracking", "customer_card")
            if constrain_width
            else ""
        )
        with (
            ui.column()
            .classes(
                f"{UI_STYLES.get_layout_classes('time_tracking_customer_column')} flex-1 min-h-0"
            )
            .style(column_style)
        ):
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
    """Full width/height main page card with consistent styling.

    Args:
        scrollable: Whether to enable vertical scrolling (default: True)
    """
    overflow_style = "overflow-y: auto;" if scrollable else "overflow-y: hidden;"

    if scrollable:
        # For scrollable content: use flex-1 to fill available space in flex containers
        style = f"min-height: 0; box-sizing: border-box; {overflow_style}"
    else:
        # For non-scrollable (internal scrolling): use fixed height calc
        # 170px accounts for navbar (~100px) + toolbar (~50px) + margins (~20px)
        style = f"height: calc(100vh - 170px); box-sizing: border-box; {overflow_style}"

    with (
        (ui.card().classes("w-full mx-4 my-4 rounded-md flex flex-col"))
        .style(style)
        .props("flat")
    ):
        yield
