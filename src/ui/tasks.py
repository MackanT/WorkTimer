"""
Task Management UI Module

Handles the task management interface including:
- Card and table views of tasks
- Task creation and editing forms
- Task filtering and sorting
- Task completion tracking
"""

import asyncio
from nicegui import ui

from ..globals import GlobalRegistry
from .. import helpers


def ui_tasks():
    """Main UI for task management with card/table views and creation form."""
    # Get global instances from registry
    AD = GlobalRegistry.get("AD")
    QE = GlobalRegistry.get("QE")
    LOG = GlobalRegistry.get("LOG")

    # Get configs from registry
    config_tasks = (
        GlobalRegistry.get("config_tasks") if GlobalRegistry.get("config_tasks") else {}
    )
    config_task_visuals = (
        GlobalRegistry.get("config_task_visuals")
        if GlobalRegistry.get("config_task_visuals")
        else {}
    )

    # Get UI_STYLES from helpers
    UI_STYLES = helpers.UI_STYLES

    # Callback functions for task interactions
    def on_task_checkbox_click(task_id, checked):
        """Handle task completion checkbox"""
        print(
            f"Task {task_id} marked as {'completed' if checked else 'incomplete'}: {checked}"
        )

        # Run completion update in background without awaiting
        asyncio.create_task(
            QE.function_db(
                "set_task_completion",
                task_id=task_id,
                completed=checked,
            )
        )

    def on_task_edit_click(task_id):
        """Handle edit task button click"""
        print(f"Edit task {task_id}")

        # Switch to edit mode
        async def switch_to_edit_mode():
            try:
                # Fetch task data from database
                task_df = await QE.query_db(
                    f"select * from tasks where task_id = {task_id}"
                )

                if task_df is not None and not task_df.empty:
                    task_data = task_df.iloc[0].to_dict()

                    edit_state["mode"] = "edit"
                    edit_state["task_id"] = task_id
                    edit_state["task_data"] = task_data

                    form_title.text = f"Edit Task: {task_data.get('title', 'Unknown')}"
                    build_task_form()
                else:
                    ui.notify(f"Task {task_id} not found!", color="negative")

            except Exception as e:
                ui.notify(f"Error loading task {task_id}: {e}", color="negative")

        # Run the async function
        asyncio.create_task(switch_to_edit_mode())

    def on_task_click(task_id):
        """Handle task card click for details view"""
        print(f"View details for task {task_id}")
        # TODO: Open task details dialog
        ui.notify(f"Task details for {task_id} - Feature coming soon!", color="info")

    with ui.splitter(value=65).classes("w-full h-full") as splitter:
        with splitter.before:
            with ui.element().classes("p-4 w-full h-full"):
                # View state - True for cards, False for table
                view_is_cards = {"value": True}

                edit_state = {
                    "mode": "add",  # "add" or "edit"
                    "task_id": None,
                    "task_data": {},
                }

                # This will be redefined after form_title and build_task_form are available
                switch_to_add_mode = None

                with ui.row().classes("w-full justify-between items-center mb-4"):
                    ui.label("Tasks").classes(UI_STYLES.get_layout_classes("title"))

                    # Sorting controls in the middle
                    with ui.row().classes("items-center gap-2"):
                        ui.label("Sort by:").classes("text-sm text-gray-400")
                        sort_options = ui.select(
                            options=[
                                "Due Date",
                                "Priority",
                                "Status",
                                "Customer",
                                "Project",
                                "Created",
                            ],
                            value="Due Date",
                        ).classes("w-32")

                        def on_sort_change(e):
                            current_sort["value"] = sort_options.value
                            ui.timer(0.1, refresh_tasks, once=True)

                        sort_options.on("update:model-value", on_sort_change)

                    # Right side buttons
                    with ui.row().classes("gap-2"):
                        # Refresh button
                        refresh_button = (
                            ui.button("", icon="refresh")
                            .classes("w-10 h-10 flex-none")
                            .props("flat")
                        )
                        refresh_button.on_click(
                            lambda: ui.timer(0.1, refresh_tasks, once=True)
                        )
                        # View toggle button
                        view_toggle = (
                            ui.button("", icon="view_module")
                            .classes("w-10 h-10 flex-none")
                            .props("flat")
                        )
                        # Add Task button (to switch back to add mode)
                        add_task_button = (
                            ui.button("", icon="add")
                            .classes("w-10 h-10 flex-none")
                            .props("flat")
                        )

                # Container for the task content (will be updated based on view) - force full width
                task_container = ui.element().classes("w-full min-w-0")

                # State to hold tasks data
                tasks_data = {"tasks": []}
                current_sort = {"value": "Due Date"}

                def create_fallback_task(
                    task_id, title, description, status, priority="N/A", completed=False
                ):
                    """Create a standardized fallback task for error/no-data scenarios"""
                    return {
                        "task_id": task_id,
                        "completed": completed,
                        "columns": [
                            {"label": "Title", "value": title},
                            {"label": "Description", "value": description},
                            {"label": "Status", "value": status},
                            {"label": "Priority", "value": priority},
                            {"label": "Assignee", "value": ""},
                            {"label": "Customer", "value": ""},
                            {"label": "Project", "value": ""},
                            {"label": "Due Date", "value": ""},
                            {"label": "Created", "value": ""},
                        ],
                    }

                def get_sort_query(sort_by):
                    """Generate SQL ORDER BY clause based on sort selection"""
                    sort_queries = {
                        "Due Date": """
                            case when due_date is null or due_date = '' then 1 else 0 end,
                            due_date asc,
                            created_at desc
                        """,
                        "Priority": """
                            case priority
                                when 'Critical' then 1
                                when 'High' then 2  
                                when 'Medium' then 3
                                when 'Low' then 4
                                else 5
                            end asc,
                            due_date asc
                        """,
                        "Status": """
                            case status
                                when 'In Progress' then 1
                                when 'To Do' then 2
                                when 'In Review' then 3
                                when 'Blocked' then 4
                                when 'On Hold' then 5
                                else 6
                            end asc,
                            due_date asc
                        """,
                        "Customer": "customer_name asc, project_name asc, due_date asc",
                        "Project": "project_name asc, customer_name asc, due_date asc",
                        "Created": "created_at desc",
                    }
                    return sort_queries.get(sort_by, sort_queries["Due Date"])

                async def fetch_tasks(sort_by="Due Date"):
                    """Fetch tasks from database and transform to UI format"""
                    try:
                        # Fetch all tasks from database with dynamic sorting
                        order_clause = get_sort_query(sort_by)
                        tasks_df = await QE.query_db(f"""
                            select * from tasks 
                            order by {order_clause}
                        """)

                        if tasks_df is not None and not tasks_df.empty:
                            tasks_list = []
                            for _, row in tasks_df.iterrows():
                                # Transform database row to UI format
                                task = {
                                    "task_id": str(row.get("task_id", "")),
                                    "completed": bool(row.get("completed", False)),
                                    "columns": [
                                        {
                                            "label": "Title",
                                            "value": str(row.get("title", "")),
                                        },
                                        {
                                            "label": "Description",
                                            "value": str(row.get("description", "")),
                                        },
                                        {
                                            "label": "Status",
                                            "value": str(row.get("status", "")),
                                        },
                                        {
                                            "label": "Priority",
                                            "value": str(row.get("priority", "")),
                                        },
                                        {
                                            "label": "Assignee",
                                            "value": str(row.get("assigned_to", "")),
                                        },
                                        {
                                            "label": "Customer",
                                            "value": str(row.get("customer_name", "")),
                                        },
                                        {
                                            "label": "Project",
                                            "value": str(row.get("project_name", "")),
                                        },
                                        {
                                            "label": "Due Date",
                                            "value": str(row.get("due_date", "")),
                                        },
                                        {
                                            "label": "Created",
                                            "value": str(row.get("created_at", "")),
                                        },
                                    ],
                                }
                                tasks_list.append(task)

                            tasks_data["tasks"] = tasks_list
                        else:
                            # Fallback to sample data if no database results
                            tasks_data["tasks"] = [
                                create_fallback_task(
                                    "NO_DATA",
                                    "No tasks found",
                                    "Add some tasks to get started",
                                    "Info",
                                )
                            ]
                    except Exception as e:
                        ui.notify(f"Error fetching tasks: {e}", color="negative")
                        tasks_data["tasks"] = [
                            create_fallback_task(
                                "ERROR",
                                "Error loading tasks",
                                f"Database error: {e}",
                                "Error",
                            )
                        ]

                def update_view_icon():
                    """Update the toggle button icon based on current view"""
                    if view_is_cards["value"]:
                        view_toggle.props(
                            "icon=view_list"
                        )  # Show table icon when in card view
                    else:
                        view_toggle.props(
                            "icon=view_module"
                        )  # Show card icon when in table view

                def render_card_view():
                    """Render tasks in true grid layout"""
                    with (
                        ui.scroll_area()
                        .classes("w-full")
                        .style("height: 600px; min-width: 0;")
                    ):
                        # Use CSS Grid for proper grid layout
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
                            for task in tasks_data["tasks"]:
                                helpers.create_task_card(
                                    task_id=task["task_id"],
                                    columns=task["columns"],
                                    completed=task.get("completed", False),
                                    on_checkbox_click=on_task_checkbox_click,
                                    on_edit_click=on_task_edit_click,
                                    on_card_click=on_task_click,
                                    config_task_visuals=config_task_visuals,
                                )

                def render_table_view():
                    """Render tasks in table layout"""
                    # Create table data
                    table_data = []
                    for task in tasks_data["tasks"]:
                        row = {
                            "task_id": task["task_id"],
                            "selected": task.get("completed", False),
                        }
                        for col in task["columns"]:
                            row[col["label"]] = col["value"]
                        table_data.append(row)

                    # Get table columns configuration from config
                    columns = []
                    if (
                        "table" in config_tasks.get("task", {})
                        and "columns" in config_tasks["task"]["table"]
                    ):
                        for col_config in config_tasks["task"]["table"]["columns"]:
                            column = {
                                "name": col_config["name"],
                                "label": col_config["label"],
                                "field": col_config["field"],
                                "align": col_config["align"],
                                "style": col_config["style"],
                            }
                            # Only add sortable if it's True
                            if col_config.get("sortable", False):
                                column["sortable"] = True
                            columns.append(column)
                    else:
                        # Fallback to hardcoded columns if config is not available
                        columns = [
                            {
                                "name": "selected",
                                "label": "",
                                "field": "selected",
                                "align": "left",
                                "style": "width: 60px;",
                            },
                            {
                                "name": "task_id",
                                "label": "ID",
                                "field": "task_id",
                                "align": "left",
                                "sortable": True,
                                "style": "width: 100px;",
                            },
                            {
                                "name": "Title",
                                "label": "Title",
                                "field": "Title",
                                "align": "left",
                                "sortable": True,
                                "style": "min-width: 200px;",
                            },
                        ]

                    # Create table with custom row rendering
                    with (
                        ui.scroll_area()
                        .classes("w-full")
                        .style("height: 600px; min-width: 0;")
                    ):
                        table = ui.table(
                            columns=columns, rows=table_data, pagination=20
                        )
                        table.classes("w-full min-w-full")
                        table.style("min-width: 800px;")

                        # Add custom cell templates
                        table.add_slot(
                            "body-cell-selected",
                            """
                            <q-td :props="props">
                                <q-checkbox v-model="props.row.selected" 
                                           @update:model-value="(val) => $parent.$emit('checkbox-change', props.row.task_id, val)" />
                            </q-td>
                        """,
                        )

                        table.add_slot(
                            "body-cell-actions",
                            """
                            <q-td :props="props">
                                <q-btn flat dense icon="edit" size="sm"
                                       @click="$parent.$emit('edit-click', props.row.task_id)" />
                            </q-td>
                        """,
                        )

                        # Handle table events
                        table.on(
                            "checkbox-change",
                            lambda e: on_task_checkbox_click(e.args[0], e.args[1]),
                        )
                        table.on("edit-click", lambda e: on_task_edit_click(e.args[0]))
                        table.on(
                            "rowClick",
                            lambda e: on_task_click(e.args[1]["task_id"])
                            if len(e.args) > 1
                            else None,
                        )

                async def refresh_tasks():
                    """Refresh tasks from database and update current view"""
                    await fetch_tasks(current_sort["value"])
                    task_container.clear()

                    with task_container:
                        if view_is_cards["value"]:
                            render_card_view()
                        else:
                            render_table_view()

                async def add_new_task_to_view(task_data):
                    """Add a single new task to the existing view without full refresh"""
                    # Create task object in the expected format
                    new_task = {
                        "task_id": str(task_data.get("task_id", "")),
                        "completed": bool(task_data.get("completed", False)),
                        "columns": [
                            {
                                "label": "Title",
                                "value": str(task_data.get("title", "")),
                            },
                            {
                                "label": "Description",
                                "value": str(task_data.get("description", "")),
                            },
                            {
                                "label": "Status",
                                "value": str(task_data.get("status", "")),
                            },
                            {
                                "label": "Priority",
                                "value": str(task_data.get("priority", "")),
                            },
                            {
                                "label": "Assignee",
                                "value": str(task_data.get("assigned_to", "")),
                            },
                            {
                                "label": "Customer",
                                "value": str(task_data.get("customer_name", "")),
                            },
                            {
                                "label": "Project",
                                "value": str(task_data.get("project_name", "")),
                            },
                            {
                                "label": "Due Date",
                                "value": str(task_data.get("due_date", "")),
                            },
                            {
                                "label": "Created",
                                "value": str(task_data.get("created_at", "")),
                            },
                        ],
                    }

                    # Remove "no data" placeholder if it exists
                    if len(tasks_data["tasks"]) == 1 and tasks_data["tasks"][0][
                        "task_id"
                    ] in ["NO_DATA", "ERROR"]:
                        tasks_data["tasks"] = []

                    # Add new task to the beginning of the list
                    tasks_data["tasks"].insert(0, new_task)

                    # Re-render the current view
                    task_container.clear()
                    with task_container:
                        if view_is_cards["value"]:
                            render_card_view()
                        else:
                            render_table_view()

                def clear_form_fields(widgets):
                    """Clear form fields instead of rebuilding entire form"""
                    for widget_name, widget in widgets.items():
                        if hasattr(widget, "value"):
                            if widget_name in ["status", "priority"]:
                                # Reset to default values for select widgets
                                widget.value = (
                                    "To Do" if widget_name == "status" else "Medium"
                                )
                            elif widget_name == "estimated_hours":
                                widget.value = 0
                            else:
                                widget.value = ""

                def toggle_view():
                    """Toggle between card and table view"""
                    view_is_cards["value"] = not view_is_cards["value"]
                    task_container.clear()

                    with task_container:
                        if view_is_cards["value"]:
                            render_card_view()
                        else:
                            render_table_view()

                    update_view_icon()

                # Bind toggle button
                view_toggle.on_click(toggle_view)

                # Initialize view with data
                async def initialize_tasks():
                    update_view_icon()
                    await refresh_tasks()

                # Start initialization using NiceGUI's timer (runs once after UI is ready)
                ui.timer(0.1, lambda: None).single_shot = True
                ui.timer(0.2, initialize_tasks, once=True)
        with splitter.after:
            # Task creation form in the right panel
            with ui.element().classes("p-4 w-full h-full"):
                # Dynamic title that changes based on mode
                form_title = ui.label("Add New Task").classes(
                    UI_STYLES.get_layout_classes("title")
                )

                # Container for the task creation form
                task_form_container = ui.element()

                def build_task_form():
                    """Build the task creation form"""
                    task_form_container.clear()

                    with task_form_container:
                        # Data preparation function (reuse existing logic)
                        def prep_task_data(tab_type, fields):
                            """Prepare data sources for task dialog"""
                            if not hasattr(AD, "df") or AD.df is None or AD.df.empty:
                                LOG.log_msg(
                                    "WARNING", "No customer/project data available"
                                )
                                return {}

                            active_data = helpers.filter_df(AD.df, {"c_current": 1})
                            if active_data.empty:
                                LOG.log_msg(
                                    "WARNING", "No active customer/project data"
                                )
                                return {}

                            # Build customer list
                            customer_rows = active_data[
                                ["customer_id", "customer_name"]
                            ].drop_duplicates()
                            customer_list = [
                                row["customer_name"]
                                for _, row in customer_rows.iterrows()
                            ]

                            # Build project mapping by customer_name
                            project_names = {}
                            for _, cust_row in customer_rows.iterrows():
                                customer_id = cust_row["customer_id"]
                                customer_name = cust_row["customer_name"]

                                filtered = helpers.filter_df(
                                    active_data,
                                    {"customer_id": customer_id, "p_current": 1},
                                )
                                project_list = []
                                if not filtered.empty:
                                    for _, proj_row in (
                                        filtered[["project_id", "project_name"]]
                                        .drop_duplicates()
                                        .iterrows()
                                    ):
                                        project_list.append(proj_row["project_name"])
                                project_names[customer_name] = project_list

                            LOG.log_msg(
                                "DEBUG",
                                f"Task form - Found {len(customer_list)} customers: {customer_list}",
                            )
                            LOG.log_msg(
                                "DEBUG", f"Task form - Project mapping: {project_names}"
                            )

                            result_data = {
                                "customer_data": customer_list,
                                "project_names": project_names,
                            }

                            # If in edit mode, add the existing task data as defaults
                            if edit_state["mode"] == "edit" and edit_state["task_data"]:
                                task_data = edit_state["task_data"]
                                result_data.update(
                                    {
                                        "default_title": task_data.get("title", ""),
                                        "default_description": task_data.get(
                                            "description", ""
                                        ),
                                        "default_status": task_data.get(
                                            "status", "To Do"
                                        ),
                                        "default_priority": task_data.get(
                                            "priority", "Medium"
                                        ),
                                        "default_assigned_to": task_data.get(
                                            "assigned_to", ""
                                        ),
                                        "default_customer_name": task_data.get(
                                            "customer_name", ""
                                        ),
                                        "default_project_name": task_data.get(
                                            "project_name", ""
                                        ),
                                        "default_due_date": task_data.get(
                                            "due_date", ""
                                        ),
                                        "default_estimated_hours": task_data.get(
                                            "estimated_hours", 0
                                        ),
                                        "default_tags": task_data.get("tags", ""),
                                    }
                                )

                            return result_data

                        # Custom task save handler (handles both insert and update)
                        async def save_task(widgets):
                            """Save task to database - handles both create and update"""
                            try:
                                task_data = helpers.parse_widget_values(widgets)

                                if edit_state["mode"] == "edit":
                                    # Update existing task (note: customer/project can't be changed in edit mode)
                                    result = await QE.function_db(
                                        "update_task",
                                        task_id=edit_state["task_id"],
                                        title=task_data.get("title", ""),
                                        description=task_data.get("description", ""),
                                        status=task_data.get("status", "To Do"),
                                        priority=task_data.get("priority", "Medium"),
                                        assigned_to=task_data.get("assigned_to", ""),
                                        due_date=task_data.get("due_date", ""),
                                        estimated_hours=float(
                                            task_data.get("estimated_hours", 0) or 0
                                        ),
                                        tags=task_data.get("tags", ""),
                                        updated_by="UI_User",
                                    )

                                    # Handle update result (success, message)
                                    success = result[0]
                                    message = result[1]

                                    if success:
                                        ui.notify(
                                            f"Task '{task_data.get('title', 'Untitled')}' updated successfully!",
                                            color="positive",
                                        )
                                        # Switch back to add mode and refresh tasks
                                        edit_state["mode"] = "add"
                                        edit_state["task_id"] = None
                                        edit_state["task_data"] = {}
                                        form_title.text = "Add New Task"

                                        # Refresh the task list to show updated data
                                        await refresh_tasks()

                                        # Rebuild form in add mode
                                        build_task_form()

                                        return True, message
                                    else:
                                        return False, message

                                else:
                                    # Insert new task
                                    result = await QE.function_db(
                                        "insert_task",
                                        title=task_data.get("title", ""),
                                        description=task_data.get("description", ""),
                                        status=task_data.get("status", "To Do"),
                                        priority=task_data.get("priority", "Medium"),
                                        assigned_to=task_data.get("assigned_to", ""),
                                        customer_name=task_data.get(
                                            "customer_name", ""
                                        ),
                                        project_name=task_data.get("project_name", ""),
                                        due_date=task_data.get("due_date", ""),
                                        estimated_hours=float(
                                            task_data.get("estimated_hours", 0) or 0
                                        ),
                                        tags=task_data.get("tags", ""),
                                        created_by="UI_User",
                                    )

                                    # Handle the insert return format (success, message, task_data)
                                    success = result[0]
                                    message = result[1]
                                    new_task_data = (
                                        result[2] if len(result) > 2 else None
                                    )

                                    if success:
                                        ui.notify(
                                            f"Task '{task_data.get('title', 'Untitled')}' created successfully!",
                                            color="positive",
                                        )
                                        # Efficiently add new task to view and clear form
                                        if new_task_data:
                                            await add_new_task_to_view(new_task_data)
                                        clear_form_fields(widgets)
                                        return True, message
                                    else:
                                        return False, message

                            except Exception as e:
                                action = (
                                    "updating"
                                    if edit_state["mode"] == "edit"
                                    else "creating"
                                )
                                return False, f"Error {action} task: {e}"

                        # Function to populate form fields in edit mode
                        def populate_form_for_edit(widgets, task_data):
                            """Populate form widgets with existing task data"""
                            if not widgets or not task_data:
                                return

                            # Get the project_names data from the prep function
                            prep_data = prep_task_data("Add", {})
                            project_names_dict = prep_data.get("project_names", {})

                            # First, populate non-dependent fields
                            simple_fields = {
                                "title": "title",
                                "description": "description",
                                "status": "status",
                                "priority": "priority",
                                "assigned_to": "assigned_to",
                                "due_date": "due_date",
                                "estimated_hours": "estimated_hours",
                                "tags": "tags",
                            }

                            for field_name, data_key in simple_fields.items():
                                if field_name in widgets and data_key in task_data:
                                    widget = widgets[field_name]
                                    value = task_data[data_key]

                                    if hasattr(widget, "value") and value is not None:
                                        if field_name == "estimated_hours":
                                            widget.value = float(value) if value else 0
                                        else:
                                            widget.value = value or ""
                                        widget.update()

                            # Handle customer and project dependency
                            customer_name = task_data.get("customer_name", "")
                            project_name = task_data.get("project_name", "")

                            if customer_name and "customer_name" in widgets:
                                customer_widget = widgets["customer_name"]
                                customer_widget.value = customer_name
                                customer_widget.update()

                                # Update project dropdown options for this customer
                                if (
                                    "project_name" in widgets
                                    and customer_name in project_names_dict
                                ):
                                    project_widget = widgets["project_name"]
                                    project_options = project_names_dict[customer_name]

                                    # Set the project dropdown options
                                    if hasattr(project_widget, "options"):
                                        project_widget.options = project_options
                                        project_widget.update()

                                    # Set the project value after options are updated
                                    def set_project_value():
                                        if project_name in project_options:
                                            project_widget.value = project_name
                                            project_widget.update()

                                    # Small delay to ensure options are set first
                                    ui.timer(0.1, set_project_value, once=True)

                        # Custom handlers for task operations (use same handler for both add and update)
                        custom_handlers = {
                            "insert_task": save_task,
                            "update_task": save_task,  # Same handler handles both cases
                        }

                        # Determine tab type and container key based on edit mode
                        tab_type = "Update" if edit_state["mode"] == "edit" else "Add"
                        container_key = tab_type

                        # Container for the form
                        form_container_dict = {container_key: ui.element()}

                        # Use the generic tab panel builder (without dialog)
                        widgets = helpers.build_generic_tab_panel(
                            entity_name="task",
                            tab_type=tab_type,
                            container_dict=form_container_dict,
                            config_source=config_tasks,
                            data_prep_func=prep_task_data,
                            custom_handlers=custom_handlers,
                            container_size="md",
                        )

                        # If in edit mode, populate the form fields with existing data
                        if (
                            edit_state["mode"] == "edit"
                            and edit_state["task_data"]
                            and widgets
                        ):
                            populate_form_for_edit(widgets, edit_state["task_data"])

                        # Add Cancel button for edit mode inside the form container
                        if edit_state["mode"] == "edit":
                            with form_container_dict[container_key]:
                                with ui.row().classes("w-full justify-end mt-4"):
                                    ui.button(
                                        "Cancel Edit",
                                        icon="cancel",
                                        on_click=lambda: switch_to_add_mode(),
                                    ).props("color=grey")

                            # Add informational text about edit mode
                            ui.label(
                                f"Editing Task ID: {edit_state['task_id']}"
                            ).classes("text-sm text-gray-400 mt-2")

                # Initialize the form after AD data is ready
                async def init_task_form():
                    await AD.refresh()
                    build_task_form()

                ui.timer(0.1, init_task_form, once=True)

                # Define the switch_to_add_mode function now that all dependencies are available
                def switch_to_add_mode():
                    """Switch back to add task mode"""
                    edit_state["mode"] = "add"
                    edit_state["task_data"] = None
                    form_title.text = "Add New Task"
                    build_task_form()

                # Connect the Add Task button to the switch function
                add_task_button.on_click(switch_to_add_mode)
