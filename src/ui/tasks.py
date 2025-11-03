"""
Task management UI with card/table views and CRUD operations.

Refactored to use DataPrepRegistry and EntityFormBuilder pattern.
Uses config_tasks.yml for form definitions.
"""

import asyncio
from datetime import datetime, timedelta

from nicegui import ui

from ..globals import GlobalRegistry
from .data_registry import DataPrepRegistry
from .form_builder import EntityFormBuilder
from .. import helpers

# ============================================================================
# Data Preparation Functions
# ============================================================================


@DataPrepRegistry.register("task", "Add")
def prep_task_add_data(**kwargs):
    """Prepare data sources for adding a new task."""
    AD = GlobalRegistry.get("AD")
    LOG = GlobalRegistry.get("LOG")

    if not AD or AD.df is None or AD.df.empty:
        if LOG:
            LOG.log_msg("WARNING", "No customer/project data available for task add")
        return {}

    # Get active customers and projects from AD.df
    active_data = helpers.filter_df(AD.df, {"c_current": 1})
    customer_names = helpers.get_unique_list(active_data, "customer_name")

    # Build project names per customer
    project_names = {}
    for customer in customer_names:
        filtered = helpers.filter_df(
            active_data, {"customer_name": customer, "p_current": 1}
        )
        project_names[customer] = helpers.get_unique_list(filtered, "project_name")

    # Set default due date to tomorrow
    default_due_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    return {
        "customer_data": customer_names,
        "project_names": project_names,
        "due_date": default_due_date,
        "today": datetime.now().strftime("%Y-%m-%d"),
        "priority": 2,  # Default: Medium
        "completed": 0,  # Default: Not completed
    }


@DataPrepRegistry.register("task", "Update")
def prep_task_update_data(**kwargs):
    """Prepare data sources for updating a task."""
    AD = GlobalRegistry.get("AD")
    LOG = GlobalRegistry.get("LOG")

    if not AD or AD.df is None or AD.df.empty:
        if LOG:
            LOG.log_msg("WARNING", "No customer/project data available for task update")
        return {}

    # Get active customers and projects from AD.df
    active_data = helpers.filter_df(AD.df, {"c_current": 1})
    customer_names = helpers.get_unique_list(active_data, "customer_name")

    # Build project names per customer
    project_names = {}
    for customer in customer_names:
        filtered = helpers.filter_df(
            active_data, {"customer_name": customer, "p_current": 1}
        )
        project_names[customer] = helpers.get_unique_list(filtered, "project_name")

    result = {
        "customer_data": customer_names,
        "project_names": project_names,
        "today": datetime.now().strftime("%Y-%m-%d"),
        # Task list will be populated lazily when Update tab is first accessed
        "task_list": [],
        "task_title": {},
        "task_description": {},
        "task_status": {},
        "task_priority": {},
        "task_assigned_to": {},
        "task_due_date": {},
        "task_estimated_hours": {},
        "task_tags": {},
    }

    return result


@DataPrepRegistry.register("task", "Delete")
def prep_task_delete_data(**kwargs):
    """Prepare data sources for deleting a task."""
    # TODO: Get task data for dropdown
    # For now, return empty - tasks need to be loaded async
    return {
        "task_data": {},
    }


# ============================================================================
# Custom Action Handlers
# ============================================================================


async def handle_update_task(widgets: dict) -> tuple[bool, str]:
    """
    Custom handler for updating a task.
    Extracts task_id from task_selector and calls database update function.
    
    Args:
        widgets: Dictionary of form widgets
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    import re
    from ..globals import GlobalRegistry
    
    QE = GlobalRegistry.get("QE")
    LOG = GlobalRegistry.get("LOG")
    
    if not QE:
        return False, "Database not available"
    
    try:
        # Extract task_id from task_selector value "Title (ID: 5)"
        task_selector_value = widgets.get("task_selector").value
        match = re.search(r'\(ID: (\d+)\)', str(task_selector_value))
        
        if not match:
            return False, "Could not extract task ID from selection"
        
        task_id = int(match.group(1))
        
        # Collect field values (excluding task_selector)
        kwargs = {
            "task_id": task_id,
            "title": widgets["title"].value,
            "description": widgets["description"].value,
            "status": widgets["status"].value,
            "priority": widgets["priority"].value,
            "assigned_to": widgets["assigned_to"].value,
            "due_date": widgets["due_date"].value,
            "estimated_hours": widgets["estimated_hours"].value,
            "tags": widgets["tags"].value,
        }
        
        # Call database update function
        await QE.function_db("update_task", **kwargs)
        
        if LOG:
            LOG.log_msg("INFO", f"Successfully updated task {task_id}: {kwargs['title']}")
        
        return True, f"Task '{kwargs['title']}' updated successfully"
        
    except Exception as e:
        if LOG:
            LOG.log_msg("ERROR", f"Failed to update task: {e}")
        return False, f"Failed to update task: {str(e)}"


# ============================================================================
# Task View Management (Card/Table)
# ============================================================================

# Global state for view management
view_is_cards = {"value": True}  # Default to card view


def get_sort_query(sort_by: str) -> str:
    """Get SQL ORDER BY clause based on sort selection."""
    sort_queries = {
        "Due Date (Earliest First)": "ORDER BY due_date ASC",  ## TODO make due_date = NULL last
        "Due Date (Latest First)": "ORDER BY due_date DESC",  ## TODO make due_date = NULL last
        "Priority (High to Low)": "ORDER BY priority ASC",
        "Priority (Low to High)": "ORDER BY priority DESC",
        "Status": "ORDER BY completed ASC, due_date ASC",
        "Customer": "ORDER BY customer_name ASC, due_date ASC",
        "Project": "ORDER BY project_name ASC, due_date ASC",
        "Created (Newest First)": "ORDER BY created_at DESC",
        "Created (Oldest First)": "ORDER BY created_at ASC",
    }
    return sort_queries.get(sort_by, "ORDER BY due_date ASC")


async def fetch_tasks(sort_by: str = "Due Date (Earliest First)") -> list[dict]:
    """Fetch tasks from database with customer/project names."""
    db = GlobalRegistry.get("QE")
    LOG = GlobalRegistry.get("LOG")

    if not db:
        if LOG:
            LOG.log_msg("ERROR", "Database not available")
        return []

    # Query just tasks table - customer_name and project_name are already in tasks
    query = f"""
        SELECT * FROM tasks 
        {get_sort_query(sort_by)}
    """

    # QueryEngine.query_db is async
    df = await db.query_db(query)

    if LOG:
        if df is None:
            LOG.log_msg("WARNING", "fetch_tasks: query returned None")
        elif df.empty:
            LOG.log_msg("WARNING", "fetch_tasks: query returned empty dataframe")
        else:
            LOG.log_msg("INFO", f"fetch_tasks: Retrieved {len(df)} tasks")

    if df is None or df.empty:
        return []

    # Transform database rows to UI format with columns array
    tasks_list = []
    for _, row in df.iterrows():
        task = {
            "task_id": str(row.get("task_id", "")),
            "completed": bool(row.get("completed", False)),
            "columns": [
                {"label": "Title", "value": str(row.get("title", ""))},
                {"label": "Description", "value": str(row.get("description", ""))},
                {"label": "Status", "value": str(row.get("status", ""))},
                {"label": "Priority", "value": str(row.get("priority", ""))},
                {"label": "Assignee", "value": str(row.get("assigned_to", ""))},
                {"label": "Customer", "value": str(row.get("customer_name", ""))},
                {"label": "Project", "value": str(row.get("project_name", ""))},
                {"label": "Due Date", "value": str(row.get("due_date", ""))},
                {"label": "Created", "value": str(row.get("created_at", ""))},
            ],
        }
        tasks_list.append(task)

    return tasks_list


def create_fallback_task(task_id: int) -> dict:
    """Create a fallback task dictionary for error recovery."""
    return {
        "task_id": task_id,
        "task_title": "Unknown Task",
        "task_description": "",
        "customer_id": None,
        "customer_name": "Unknown",
        "project_id": None,
        "project_name": "Unknown",
        "priority": 2,
        "due_date": datetime.now().strftime("%Y-%m-%d"),
        "completed": 0,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def on_task_checkbox_click(task_id: int, checked: bool):
    """Handle task completion checkbox click (non-async wrapper)."""

    async def _update_task():
        db = GlobalRegistry.get("QE")
        LOG = GlobalRegistry.get("LOG")

        if not db:
            if LOG:
                LOG.log_msg("ERROR", "Database not available")
            return

        try:
            await db.function_db(
                "set_task_completion",
                task_id=task_id,
                completed=checked,
            )
            status = "completed" if checked else "incomplete"
            if LOG:
                LOG.log_msg("INFO", f"Task {task_id} marked as {status}")
            await refresh_tasks()
        except Exception as e:
            if LOG:
                LOG.log_msg("ERROR", f"Failed to update task completion: {e}")

    asyncio.create_task(_update_task())


def on_task_edit_click(task_id: int):
    """Handle task edit button click - switches to Update tab and selects the task."""

    async def _switch_to_update():
        db = GlobalRegistry.get("QE")
        LOG = GlobalRegistry.get("LOG")
        tabs = GlobalRegistry.get("task_tabs")
        update_widgets = GlobalRegistry.get("task_update_widgets")

        if not db or not tabs or not update_widgets:
            if LOG:
                LOG.log_msg(
                    "ERROR",
                    f"Required components not available: db={bool(db)}, tabs={bool(tabs)}, update_widgets={bool(update_widgets)}",
                )
            return

        try:
            # Fetch task data to get title for identifier
            task_df = await db.query_db(
                f"SELECT task_id, title FROM tasks WHERE task_id = {task_id}"
            )

            if task_df is not None and not task_df.empty:
                task_data = task_df.iloc[0].to_dict()
                task_title = task_data.get("title", "Untitled")
                task_identifier = f"{task_title} (ID: {task_id})"

                if LOG:
                    LOG.log_msg(
                        "INFO",
                        f"on_task_edit_click: Switching to Update tab for: {task_identifier}",
                    )

                # Switch to Update tab
                tabs.set_value("Update")

                # Get the task_selector widget and set its value
                task_selector = update_widgets.get("task_selector")
                if task_selector:
                    if LOG:
                        LOG.log_msg(
                            "INFO",
                            f"on_task_edit_click: Setting task_selector to: {task_identifier}",
                        )

                    # Set the value
                    task_selector.set_value(task_identifier)
                    
                    # Manually populate fields since set_value doesn't always trigger events
                    await populate_task_fields(task_identifier)

                    if LOG:
                        LOG.log_msg(
                            "INFO",
                            f"on_task_edit_click: task_selector value set to: {task_selector.value}",
                        )
                else:
                    if LOG:
                        LOG.log_msg(
                            "WARNING",
                            "on_task_edit_click: task_selector widget not found in update_widgets",
                        )
            else:
                if LOG:
                    LOG.log_msg("WARNING", f"Task {task_id} not found")
        except Exception as e:
            if LOG:
                LOG.log_msg(
                    "ERROR", f"Failed to switch to edit mode for task {task_id}: {e}"
                )

    asyncio.create_task(_switch_to_update())


async def populate_task_selector():
    """Populate the task_selector dropdown with all tasks from database."""
    db = GlobalRegistry.get("QE")
    LOG = GlobalRegistry.get("LOG")
    update_widgets = GlobalRegistry.get("task_update_widgets")

    if not db or not update_widgets:
        if LOG:
            LOG.log_msg(
                "WARNING",
                f"Cannot populate task selector: db={bool(db)}, widgets={bool(update_widgets)}",
            )
        return

    try:
        # Fetch all tasks
        tasks_df = await db.query_db("SELECT task_id, title FROM tasks ORDER BY title")

        if tasks_df is not None and not tasks_df.empty:
            # Build task list
            task_list = []
            for _, row in tasks_df.iterrows():
                task_id = row["task_id"]
                title = row["title"]
                task_identifier = f"{title} (ID: {task_id})"
                task_list.append(task_identifier)

            # Update the task_selector widget options
            task_selector = update_widgets.get("task_selector")
            if task_selector:
                task_selector.options = task_list

                # Add on_change handler to populate fields when task is selected
                async def on_task_selected():
                    if task_selector.value:
                        await populate_task_fields(task_selector.value)

                task_selector.on(
                    "update:model-value",
                    lambda: asyncio.create_task(on_task_selected()),
                )
                task_selector.update()

                if LOG:
                    LOG.log_msg(
                        "INFO",
                        f"populate_task_selector: Loaded {len(task_list)} tasks into dropdown",
                    )
            else:
                if LOG:
                    LOG.log_msg(
                        "WARNING",
                        "populate_task_selector: task_selector widget not found",
                    )
        else:
            if LOG:
                LOG.log_msg(
                    "WARNING", "populate_task_selector: No tasks found in database"
                )
    except Exception as e:
        if LOG:
            LOG.log_msg("ERROR", f"populate_task_selector: Failed to load tasks: {e}")


async def populate_task_fields(task_identifier: str):
    """Populate all task fields when a task is selected from the dropdown."""
    db = GlobalRegistry.get("QE")
    LOG = GlobalRegistry.get("LOG")
    update_widgets = GlobalRegistry.get("task_update_widgets")

    if not db or not update_widgets or not task_identifier:
        return

    try:
        # Extract task_id from identifier "Title (ID: 5)"
        import re

        match = re.search(r"\(ID: (\d+)\)", task_identifier)
        if not match:
            if LOG:
                LOG.log_msg(
                    "WARNING",
                    f"populate_task_fields: Could not extract task_id from: {task_identifier}",
                )
            return

        task_id = int(match.group(1))

        if LOG:
            LOG.log_msg(
                "INFO", f"populate_task_fields: Fetching data for task_id={task_id}"
            )

        # Fetch full task data
        task_df = await db.query_db(f"SELECT * FROM tasks WHERE task_id = {task_id}")

        if task_df is not None and not task_df.empty:
            task_data = task_df.iloc[0].to_dict()

            # Populate each field widget
            field_mappings = {
                "title": "title",
                "description": "description",
                "status": "status",
                "priority": "priority",
                "assigned_to": "assigned_to",
                "due_date": "due_date",
                "estimated_hours": "estimated_hours",
                "tags": "tags",
            }

            for widget_name, db_column in field_mappings.items():
                widget = update_widgets.get(widget_name)
                if widget and db_column in task_data:
                    value = task_data[db_column]
                    if value is not None:
                        try:
                            # For select widgets (status, priority), use direct value assignment
                            # For other widgets, use set_value() or direct assignment
                            if widget_name in ["status", "priority"]:
                                # Direct assignment for select widgets
                                widget.value = value
                                widget.update()
                                if LOG:
                                    LOG.log_msg(
                                        "INFO",
                                        f"populate_task_fields: Set {widget_name} = {value} (direct)",
                                    )
                            else:
                                # For input/text/number widgets, convert to string
                                str_value = str(value)
                                widget.set_value(str_value)
                                if LOG:
                                    LOG.log_msg(
                                        "INFO",
                                        f"populate_task_fields: Set {widget_name} = {str_value}",
                                    )
                        except Exception as e:
                            if LOG:
                                LOG.log_msg(
                                    "ERROR",
                                    f"populate_task_fields: Failed to set {widget_name}: {e}",
                                )

            if LOG:
                LOG.log_msg(
                    "INFO", f"populate_task_fields: Populated fields for task {task_id}"
                )
        else:
            if LOG:
                LOG.log_msg(
                    "WARNING",
                    f"populate_task_fields: Task {task_id} not found in database",
                )
    except Exception as e:
        if LOG:
            LOG.log_msg(
                "ERROR", f"populate_task_fields: Failed to populate fields: {e}"
            )
        import traceback

        if LOG:
            LOG.log_msg(
                "ERROR", f"populate_task_fields traceback: {traceback.format_exc()}"
            )


def on_task_click(task_id: int):
    """Handle task card/row click - switches to View mode with read-only display."""

    async def _switch_to_view():
        db = GlobalRegistry.get("QE")
        LOG = GlobalRegistry.get("LOG")
        tabs = GlobalRegistry.get("task_tabs")
        view_container = GlobalRegistry.get("task_view_container")

        if not db or not tabs or not view_container:
            if LOG:
                LOG.log_msg("ERROR", "Database, tabs, or view container not available")
            return

        try:
            # Fetch task data from database
            task_df = await db.query_db(
                f"SELECT * FROM tasks WHERE task_id = {task_id}"
            )

            if task_df is not None and not task_df.empty:
                task_data = task_df.iloc[0].to_dict()

                # Clear and rebuild view container with task details
                view_container.clear()

                with view_container:
                    ui.label("Task Details").classes("text-xl font-bold mb-4")

                    # Create read-only display of task fields
                    with ui.card().classes("w-full p-4"):
                        with ui.column().classes("gap-3 w-full"):
                            # Title
                            ui.label("Title").classes("text-sm font-bold text-gray-400")
                            ui.label(str(task_data.get("title", ""))).classes(
                                "text-base mb-2"
                            )

                            # Description
                            ui.label("Description").classes(
                                "text-sm font-bold text-gray-400"
                            )
                            ui.label(str(task_data.get("description", "N/A"))).classes(
                                "text-base mb-2"
                            )

                            # Customer and Project
                            with ui.row().classes("gap-4 w-full"):
                                with ui.column().classes("flex-1"):
                                    ui.label("Customer").classes(
                                        "text-sm font-bold text-gray-400"
                                    )
                                    ui.label(
                                        str(task_data.get("customer_name", "N/A"))
                                    ).classes("text-base")
                                with ui.column().classes("flex-1"):
                                    ui.label("Project").classes(
                                        "text-sm font-bold text-gray-400"
                                    )
                                    ui.label(
                                        str(task_data.get("project_name", "N/A"))
                                    ).classes("text-base")

                            # Status and Priority
                            with ui.row().classes("gap-4 w-full mt-2"):
                                with ui.column().classes("flex-1"):
                                    ui.label("Status").classes(
                                        "text-sm font-bold text-gray-400"
                                    )
                                    ui.label(
                                        str(task_data.get("status", "N/A"))
                                    ).classes("text-base")
                                with ui.column().classes("flex-1"):
                                    ui.label("Priority").classes(
                                        "text-sm font-bold text-gray-400"
                                    )
                                    ui.label(
                                        str(task_data.get("priority", "N/A"))
                                    ).classes("text-base")

                            # Due Date
                            with ui.row().classes("gap-4 w-full mt-2"):
                                with ui.column().classes("flex-1"):
                                    ui.label("Due Date").classes(
                                        "text-sm font-bold text-gray-400"
                                    )
                                    ui.label(
                                        str(task_data.get("due_date", "N/A"))
                                    ).classes("text-base")
                                with ui.column().classes("flex-1"):
                                    ui.label("Assigned To").classes(
                                        "text-sm font-bold text-gray-400"
                                    )
                                    ui.label(
                                        str(task_data.get("assigned_to", "N/A"))
                                    ).classes("text-base")

                            # Hours
                            with ui.row().classes("gap-4 w-full mt-2"):
                                with ui.column().classes("flex-1"):
                                    ui.label("Estimated Hours").classes(
                                        "text-sm font-bold text-gray-400"
                                    )
                                    ui.label(
                                        str(task_data.get("estimated_hours", "N/A"))
                                    ).classes("text-base")
                                with ui.column().classes("flex-1"):
                                    ui.label("Actual Hours").classes(
                                        "text-sm font-bold text-gray-400"
                                    )
                                    ui.label(
                                        str(task_data.get("actual_hours", "N/A"))
                                    ).classes("text-base")

                            # Completed
                            ui.label("Completed").classes(
                                "text-sm font-bold text-gray-400 mt-2"
                            )
                            completed = task_data.get("completed", False)
                            ui.label("Yes" if completed else "No").classes("text-base")

                            # Timestamps
                            ui.label("Created").classes(
                                "text-sm font-bold text-gray-400 mt-2"
                            )
                            ui.label(str(task_data.get("created_at", "N/A"))).classes(
                                "text-sm text-gray-500"
                            )

                # Switch to View tab
                tabs.set_value("View")

                if LOG:
                    LOG.log_msg("INFO", f"Viewing task {task_id}")
            else:
                if LOG:
                    LOG.log_msg("WARNING", f"Task {task_id} not found")
        except Exception as e:
            if LOG:
                LOG.log_msg("ERROR", f"Failed to load task {task_id}: {e}")

    asyncio.create_task(_switch_to_view())


def render_card_view(tasks: list[dict], container: ui.element):
    """Render tasks in card view."""
    container.clear()

    if not tasks:
        with container:
            ui.label("No tasks found").classes("text-gray-500 text-center w-full p-8")
        return

    config_task_visuals = GlobalRegistry.get("config_task_visuals")

    with container:
        with ui.scroll_area().classes("w-full").style("height: 600px; min-width: 0;"):
            # Use CSS Grid for proper grid layout with padding
            with (
                ui.element()
                .classes("w-full")
                .style(
                    "display: grid; "
                    "grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); "
                    "gap: 16px; "
                    "padding: 8px;"
                )
            ):
                for task in tasks:
                    # Render task card
                    helpers.create_task_card(
                        task_id=task["task_id"],
                        columns=task["columns"],
                        completed=task.get("completed", False),
                        on_checkbox_click=on_task_checkbox_click,
                        on_edit_click=on_task_edit_click,
                        on_card_click=on_task_click,
                        config_task_visuals=config_task_visuals,
                    )


def render_table_view(tasks: list[dict], container: ui.element):
    """Render tasks in table view."""
    container.clear()

    if not tasks:
        with container:
            ui.label("No tasks found").classes("text-gray-500 text-center w-full p-8")
        return

    # Transform tasks from columns array format to flat field format for table
    table_data = []
    for task in tasks:
        row = {
            "task_id": task["task_id"],
            "completed": task.get("completed", False),
        }
        # Convert columns array to flat fields
        for col in task.get("columns", []):
            row[col["label"]] = col["value"]
        table_data.append(row)

    columns = [
        {"name": "completed", "label": "✓", "field": "completed", "align": "center"},
        {
            "name": "Title",
            "label": "Title",
            "field": "Title",
            "align": "left",
        },
        {
            "name": "Customer",
            "label": "Customer",
            "field": "Customer",
            "align": "left",
        },
        {
            "name": "Project",
            "label": "Project",
            "field": "Project",
            "align": "left",
        },
        {
            "name": "Priority",
            "label": "Priority",
            "field": "Priority",
            "align": "center",
        },
        {
            "name": "Due Date",
            "label": "Due Date",
            "field": "Due Date",
            "align": "center",
        },
        {"name": "Status", "label": "Status", "field": "Status", "align": "center"},
    ]

    with container:
        table = ui.table(
            columns=columns,
            rows=table_data,
            row_key="task_id",
        ).classes("w-full")

        # Custom cell rendering for checkbox
        table.add_slot(
            "body-cell-completed",
            """
            <q-td :props="props">
                <q-checkbox 
                    :model-value="props.row.completed"
                    @update:model-value="$parent.$emit('checkbox-click', props.row.task_id, $event)"
                />
            </q-td>
        """,
        )

        # Custom cell rendering for priority (handles text values)
        table.add_slot(
            "body-cell-Priority",
            """
            <q-td :props="props">
                <span v-if="props.row.Priority === 'Critical' || props.row.Priority === 'High'" class="text-red-600 font-bold">{{ props.row.Priority }}</span>
                <span v-else-if="props.row.Priority === 'Medium'" class="text-yellow-600">{{ props.row.Priority }}</span>
                <span v-else class="text-green-600">{{ props.row.Priority }}</span>
            </q-td>
        """,
        )

        # Wire up event handlers
        table.on(
            "checkbox-click", lambda e: on_task_checkbox_click(e.args[0], e.args[1])
        )


async def refresh_tasks():
    """Refresh task display."""
    tasks_container = GlobalRegistry.get("tasks_container")
    sort_select = GlobalRegistry.get("tasks_sort_select")
    LOG = GlobalRegistry.get("LOG")

    if not tasks_container:
        if LOG:
            LOG.log_msg("WARNING", "Tasks container not found for refresh")
        return

    sort_by = sort_select.value if sort_select else "Due Date (Earliest First)"
    tasks = await fetch_tasks(sort_by)

    if LOG:
        LOG.log_msg(
            "INFO",
            f"refresh_tasks: Got {len(tasks)} tasks, view_is_cards={view_is_cards['value']}",
        )

    if view_is_cards["value"]:
        render_card_view(tasks, tasks_container)
    else:
        render_table_view(tasks, tasks_container)


async def toggle_view():
    """Toggle between card and table view."""
    view_is_cards["value"] = not view_is_cards["value"]
    await refresh_tasks()


# ============================================================================
# Main Task UI Entry Point
# ============================================================================


def ui_tasks():
    """Main entry point for task management UI - called by app_layout."""
    # Get task config from GlobalRegistry (stored as config_tasks)
    task_config = GlobalRegistry.get("config_tasks")
    LOG = GlobalRegistry.get("LOG")

    if not task_config:
        if LOG:
            LOG.log_msg("ERROR", "config_tasks not found in GlobalRegistry")
        return

    # EntityFormBuilder expects config with entity_name as key
    # config_tasks.yml structure: { task: { add: {...}, update: {...} } }
    # So we pass the full task_config which contains "task" key

    # Create container dict for cross-tab widget access
    container_dict = {}
    GlobalRegistry.set("task_container_dict", container_dict)

    # Define refresh callback that reloads tasks
    async def on_task_save_success():
        """Callback after successful task save/update/delete."""
        await refresh_tasks()

    # ========================================================================
    # Main UI Layout
    # ========================================================================

    # Create main container with splitter (left: task view, right: forms)
    with ui.splitter(value=65).classes("w-full h-full") as splitter:
        # Left panel: Task view
        with splitter.before:
            with ui.element().classes("p-4 w-full h-full"):
                ui.label("Tasks").classes("text-2xl font-bold mb-4")

                # Controls row
                with ui.row().classes("w-full justify-between items-center mb-4"):
                    # Sort dropdown
                    sort_options = [
                        "Due Date (Earliest First)",
                        "Due Date (Latest First)",
                        "Priority (High to Low)",
                        "Priority (Low to High)",
                        "Status",
                        "Customer",
                        "Project",
                        "Created (Newest First)",
                        "Created (Oldest First)",
                    ]
                    sort_select = ui.select(
                        options=sort_options,
                        value="Due Date (Earliest First)",
                        on_change=lambda: refresh_tasks(),
                    ).classes("w-64")
                    GlobalRegistry.set("tasks_sort_select", sort_select)

                    # Right side: Add button and view toggle
                    with ui.row().classes("gap-2"):
                        # Add Task button
                        def switch_to_add_mode():
                            tabs = GlobalRegistry.get("task_tabs")
                            if tabs:
                                tabs.set_value("Add")
                                # Clear any stored update data
                                GlobalRegistry.set("task_update_data", None)

                        add_task_btn = ui.button(
                            icon="add",
                            on_click=switch_to_add_mode,
                        ).props("flat dense")
                        add_task_btn.tooltip("Add New Task")

                        # View toggle button
                        view_toggle_btn = ui.button(
                            icon="view_module",
                            on_click=toggle_view,
                        ).props("flat dense")
                        view_toggle_btn.tooltip("Toggle Card/Table View")

                # Tasks container
                tasks_container = ui.column().classes("w-full")
                GlobalRegistry.set("tasks_container", tasks_container)

                # Defer initial task loading to avoid sync/async issues
                # Use a timer to load tasks after UI is constructed
                ui.timer(0.1, refresh_tasks, once=True)

        # Right panel: Forms
        with splitter.after:
            with ui.element().classes("p-4 w-full h-full"):
                # Create EntityFormBuilder instance with the full task_config
                # EntityFormBuilder will look for task_config["task"] internally
                builder = EntityFormBuilder("task", task_config)

                # Create tabs
                with (
                    ui.tabs().props("inline-label align=left").classes("w-full") as tabs
                ):
                    ui.tab("Add")
                    ui.tab("Update")
                    ui.tab("View")

                # Store tabs in GlobalRegistry so click handlers can switch tabs
                GlobalRegistry.set("task_tabs", tabs)

                # Create tab panels
                with ui.tab_panels(tabs, value="Add").classes("w-full"):
                    # Add tab
                    with ui.tab_panel("Add"):
                        builder.build_form(
                            tab_type="Add",
                            container_dict=container_dict,
                            on_success_callback=on_task_save_success,
                        )

                    # Update tab
                    with ui.tab_panel("Update"):
                        update_widgets = builder.build_form(
                            tab_type="Update",
                            container_dict=container_dict,
                            custom_handlers={"update_task": handle_update_task},
                            on_success_callback=on_task_save_success,
                        )
                        # Store widgets in GlobalRegistry so edit handler can access them
                        GlobalRegistry.set("task_update_widgets", update_widgets)

                        # Populate the task_selector dropdown asynchronously
                        ui.timer(
                            0.1,
                            lambda: asyncio.create_task(populate_task_selector()),
                            once=True,
                        )

                    # View tab - read-only display of task details
                    with ui.tab_panel("View"):
                        view_container = ui.column().classes("w-full")
                        GlobalRegistry.set("task_view_container", view_container)

                        with view_container:
                            ui.label("Click a task card to view details").classes(
                                "text-gray-500"
                            )
