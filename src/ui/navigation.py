"""
Navigation Component

Provides a consistent top banner navigation for all pages.
"""

from nicegui import ui, app
from ..helpers import UI_STYLES


def create_navigation() -> None:
    """
    Create the top navigation banner with buttons to all main areas.

    Uses app.storage.client to ensure navigation is only created once per client session.
    """

    ui.query(".nicegui-content").classes("p-0 gap-0")

    try:
        # Check if navigation already created for this client session
        if app.storage.client.get("navigation_created", False):
            print("[Navigation] Navigation already created for this client, skipping")
            return

        # Mark as created for this client
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
            {"label": "Tasks", "icon": "check_box", "path": "/tasks", "key": "tasks"},
            {"label": "Log", "icon": "terminal", "path": "/log", "key": "log"},
            {"label": "Info", "icon": "info", "path": "/info", "key": "info"},
            {"label": "Test", "icon": "science", "path": "/test", "key": "test"},
        ]

        # Create header-like navigation bar using regular elements
        with ui.row().classes(
            "worktimer-navigation w-full items-center justify-between bg-gray-800 px-6 py-3 sticky top-0 z-50 shadow-lg"
        ):
            with ui.row().classes("items-center gap-1"):
                # App title
                ui.label("WorkTimer").classes("text-h6 text-white font-bold mr-4")

                # Navigation buttons
                for item in nav_items:
                    button = ui.button(
                        item["label"],
                        icon=item["icon"],
                        on_click=lambda path=item["path"]: ui.navigate.to(path),
                    ).props("flat data-path='{}'".format(item["path"]))
                    button.classes("text-gray-300 hover:bg-gray-700")

        # Inject JS to update active nav button - use ui.timer to ensure page is ready
        ui.timer(
            0.1,
            lambda: ui.run_javascript(r"""
        (function(){
            function updateNav(){
                const path = window.location.pathname || '/';
                document.querySelectorAll('[data-path]').forEach(btn=>{
                    const p = btn.getAttribute('data-path') || '/';
                    if(p === path){
                        btn.classList.add('bg-blue-700','text-white');
                        btn.classList.remove('text-gray-300','hover:bg-gray-700');
                    } else {
                        btn.classList.remove('bg-blue-700','text-white');
                        btn.classList.add('text-gray-300','hover:bg-gray-700');
                    }
                });
            }
            updateNav();
            window.addEventListener('popstate', updateNav);
            // patch pushState/replaceState to trigger update
            ['pushState','replaceState'].forEach(fn=>{
                const orig = history[fn];
                history[fn] = function(){
                    const res = orig.apply(this, arguments);
                    window.dispatchEvent(new Event('popstate'));
                    return res;
                }
            });
        })();
        """),
            once=True,
        )
    except Exception as e:
        print(f"[Navigation] ERROR creating navigation: {e}")
        import traceback

        traceback.print_exc()
