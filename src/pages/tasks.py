"""
Todo/Tasks Page

Task management interface - view and manage tasks/todos.
Uses V2 architecture with per-client AppCore and event-driven updates.
"""

from nicegui import ui
from ..core.app import AppCore, get_config_loader
from ..ui.navigation import create_navigation


@ui.page("/tasks")
async def tasks_page():
    """Tasks page - for managing todos and tasks"""

    # Get or create AppCore for this client
    config_loader = get_config_loader()
    core = AppCore.get_or_create(config_loader)

    dark = ui.dark_mode()
    dark.enable()

    # Navigation
    create_navigation()

    # Setup debug keyboard handlers
    from ..ui.keyboard_handlers import setup_debug_keyboard_handlers

    setup_debug_keyboard_handlers(core)

    # Initialize engines if needed
    if not core._initialized:
        await core.initialize_engines()

    # Main content
    with ui.column().classes("w-full p-4"):
        ui.label("Tasks & To-Do").classes("text-h4 mb-4")

        # Get tasks configuration
        tasks_config = core.tasks_config

        # Create tabs for different customers
        with ui.tabs() as tabs:
            # Create tabs from tasks config
            customer_tabs = {}
            for customer_name in tasks_config.keys():
                customer_tabs[customer_name] = ui.tab(customer_name, icon="business")

        # Tab panels
        with ui.tab_panels(
            tabs, value=list(customer_tabs.values())[0] if customer_tabs else None
        ).classes("w-full"):
            for customer_name, tab in customer_tabs.items():
                with ui.tab_panel(tab):
                    await _render_customer_tasks(
                        core, customer_name, tasks_config.get(customer_name, {})
                    )


async def _render_customer_tasks(
    core: AppCore, customer_name: str, customer_config: dict
):
    """Render tasks for a specific customer"""

    ui.label(f"Tasks for {customer_name}").classes("text-h5 mb-4")

    # Get projects for this customer
    try:
        all_projects = await core.query_engine.get_projects()
        customer_projects = all_projects[all_projects["customer_name"] == customer_name]

        if len(customer_projects) == 0:
            ui.label(f"No projects found for {customer_name}").classes("text-gray-500")
            return

        # Display projects with task checkboxes
        for _, project in customer_projects.iterrows():
            project_id = project["project_id"]
            project_name = project["project_name"]

            with ui.expansion(project_name, icon="folder").classes("w-full mb-2"):
                # Get tasks for this project from config
                project_config = customer_config.get(project_name, {})
                project_tasks = project_config.get("project", {}).get("tasks", [])

                if not project_tasks:
                    ui.label("No tasks configured for this project").classes(
                        "text-gray-500"
                    )
                else:
                    # Display task checkboxes
                    with ui.column().classes("gap-2 p-2"):
                        for task in project_tasks:
                            task_name = task.get("name", "Unnamed Task")
                            task_desc = task.get("description", "")

                            with ui.row().classes("items-center gap-2"):
                                checkbox = ui.checkbox(task_name)

                                if task_desc:
                                    ui.label(f"- {task_desc}").classes(
                                        "text-sm text-gray-500"
                                    )

                        # Add new task button
                        ui.button(
                            "Add Task",
                            icon="add",
                            on_click=lambda: _show_add_task_dialog(
                                core, project_id, project_name
                            ),
                        ).props("flat size=sm")

    except Exception as e:
        core.logger.error(f"Error loading tasks for {customer_name}: {e}")
        ui.label(f"Error loading tasks: {e}").classes("text-red-500")


def _show_add_task_dialog(core: AppCore, project_id: int, project_name: str):
    """Show dialog to add a new task"""

    with ui.dialog() as dialog, ui.card():
        ui.label(f"Add Task to {project_name}").classes("text-h6 mb-2")

        task_name = ui.input("Task Name").classes("w-full")
        task_description = ui.textarea("Description").classes("w-full")

        with ui.row().classes("gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")

            async def do_add():
                name = task_name.value
                desc = task_description.value

                if not name:
                    ui.notify("Please enter a task name", type="warning")
                    return

                try:
                    # Add task using add_data_engine
                    result = await core.add_data_engine.add_task(
                        {
                            "project_id": project_id,
                            "task_name": name,
                            "task_description": desc,
                        }
                    )

                    if result:
                        ui.notify(f"Task '{name}' added!", type="positive")
                        dialog.close()
                    else:
                        ui.notify("Failed to add task", type="negative")

                except Exception as e:
                    core.logger.error(f"Error adding task: {e}")
                    ui.notify(f"Error: {e}", type="negative")

            ui.button("Add", on_click=do_add).props("color=primary")

    dialog.open()
