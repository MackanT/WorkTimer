"""
Generalized UI Components used throughout the application.
"""

from nicegui import ui, app


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
        ui.query(".nicegui-content").classes("p-0 gap-0")

        try:
            if app.storage.client.get("navigation_created", False):
                return
            app.storage.client["navigation_created"] = True

            # Define navigation items
            nav_items = [
                {
                    "label": "Time Tracking",
                    "icon": "schedule",
                    "path": "/",
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
                {"label": "Test", "icon": "science", "path": "/test", "key": "test"},
            ]

            nav_text = self.theme.get("muted")
            nav_hover = self.theme.get("toolbar_bg")

            # Create header-like navigation bar using regular elements
            with ui.row().classes(
                f"worktimer-navigation w-full items-center justify-between bg-{self.theme.get('nav_bg')} px-6 py-3 sticky top-0 z-50 shadow-lg"
            ):
                with ui.row().classes("items-center gap-1"):
                    # App title
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
            # Get current path from the page or default to "/"
            current_path = app.storage.client.get("current_path", "/")
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
