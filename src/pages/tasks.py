"""
Task Management Page

Task management interface with card/table views and CRUD operations.
Uses V2 architecture with per-client AppCore and event-driven updates.
Fully config-driven using config_tasks.yml structure.
"""

import asyncio
import inspect
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

from nicegui import ui

from ..core.app import AppCore
from .. import helpers
from ..helpers import UI_STYLES
from ..ui.keyboard_handlers import setup_debug_keyboard_handlers
from ..ui.dynamic_widgets import (
    DynamicDropDown,
    DynamicInput,
    DynamicTextArea,
    DynamicNumber,
    DynamicDateInput,
)

from ..ui.elements import (
    toolbar,
    toolbar_group,
    entity_card_shell,
    entity_card_header,
    entity_card_content,
)

# ============================================================================
# Data Models
# ============================================================================


@dataclass
class Task:
    """
    Lightweight task data transfer object.

    Represents task data in memory for display purposes.
    DB remains the source of truth - always fetch fresh for edits.
    """

    task_id: int
    title: str
    description: str
    customer_name: str
    project_name: str
    status: str
    priority: str
    assigned_to: str
    due_date: Optional[str]
    estimated_hours: float
    actual_hours: float
    tags: str
    completed: bool
    created_at: str

    @classmethod
    def from_df_row(cls, row):
        """Create Task from pandas DataFrame row."""
        return cls(
            task_id=int(row.get("task_id", 0)),
            title=str(row.get("title", "")),
            description=str(row.get("description", "")),
            customer_name=str(row.get("customer_name", "")),
            project_name=str(row.get("project_name", "")),
            status=str(row.get("status", "")),
            priority=str(row.get("priority", "")),
            assigned_to=str(row.get("assigned_to", "")),
            due_date=str(row.get("due_date", "")) if row.get("due_date") else None,
            estimated_hours=float(row.get("estimated_hours", 0)),
            actual_hours=float(row.get("actual_hours", 0)),
            tags=str(row.get("tags", "")),
            completed=bool(row.get("completed", False)),
            created_at=str(row.get("created_at", "")),
        )

    def to_columns_format(self) -> list[dict]:
        """Convert to columns array format for card rendering."""
        return [
            {"label": "Title", "value": self.title},
            {"label": "Description", "value": self.description},
            {"label": "Status", "value": self.status},
            {"label": "Priority", "value": self.priority},
            {"label": "Assignee", "value": self.assigned_to},
            {"label": "Customer", "value": self.customer_name},
            {"label": "Project", "value": self.project_name},
            {"label": "Due Date", "value": self.due_date or ""},
            {"label": "Created", "value": self.created_at},
        ]

    def to_dict(self) -> dict:
        """Convert to dictionary for table rendering."""
        return {
            "task_id": str(self.task_id),
            "completed": self.completed,
            "Title": self.title,
            "Description": self.description,
            "Status": self.status,
            "Priority": self.priority,
            "Assignee": self.assigned_to,
            "Customer": self.customer_name,
            "Project": self.project_name,
            "Due Date": self.due_date or "",
            "Created": self.created_at,
        }


# ============================================================================
# Constants
# ============================================================================

# UI Layout Constants
SPLITTER_RATIO = 70  # Percentage for left panel (task view)
SORT_SELECT_WIDTH = "w-64"  # Width class for sort dropdown

# ============================================================================
# Helper Functions
# ============================================================================


async def get_customer_project_data(core: AppCore) -> dict:
    """
    Get active customers and project names from query engine.
    Uses same approach as add_data.py prepare_data_sources().

    Returns:
        Dictionary with customer_data (list) and project_names (dict)
    """
    try:
        # Get active customers (same query as add_data.py)
        df = await core.query_engine.query_db(
            "SELECT customer_id, customer_name FROM customers WHERE is_current = 1"
        )
        customer_data = df["customer_name"].tolist() if not df.empty else []

        # Get active projects grouped by customer (same approach as add_data.py)
        grouped_df = await core.query_engine.query_db(
            """SELECT p.project_name, c.customer_name
               FROM projects p
               JOIN customers c ON p.customer_id = c.customer_id
               WHERE p.is_current = 1"""
        )

        project_names_by_cust = {}
        if not grouped_df.empty:
            for _, row in grouped_df.iterrows():
                project_names_by_cust.setdefault(row["customer_name"], []).append(
                    row["project_name"]
                )

        return {
            "customer_data": customer_data,
            "project_names": project_names_by_cust,
        }
    except Exception as e:
        core.logger.error(f"Error getting customer/project data: {e}")
        return {"customer_data": [], "project_names": {}}


# ============================================================================
# Task View Management (Card/Table)
# ============================================================================


def get_sort_query(sort_by: str) -> str:
    """Get SQL ORDER BY clause based on sort selection."""
    sort_queries = {
        "Due Date (Earliest First)": "ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END DESC, due_date ASC",
        "Due Date (Latest First)": "ORDER BY CASE WHEN due_date IS NULL THEN 0 ELSE 1 END DESC, due_date DESC",
        "Priority (High to Low)": "ORDER BY priority ASC",
        "Priority (Low to High)": "ORDER BY priority DESC",
        "Status": "ORDER BY completed ASC, due_date ASC",
        "Customer": "ORDER BY customer_name ASC, due_date ASC",
        "Project": "ORDER BY project_name ASC, due_date ASC",
        "Created (Newest First)": "ORDER BY created_at DESC",
        "Created (Oldest First)": "ORDER BY created_at ASC",
    }
    return sort_queries.get(sort_by, "ORDER BY due_date ASC")


async def fetch_tasks(
    core: AppCore,
    sort_by: str = "Due Date (Earliest First)",
    show_completed: bool = False,
) -> list[Task]:
    """Fetch tasks from database and return Task objects."""
    try:
        where_clause = "" if show_completed else "WHERE completed = 0"

        query = f"""
            SELECT * FROM tasks 
            {where_clause}
            {get_sort_query(sort_by)}
        """

        df = await core.query_engine.query_db(query)

        if df is None or df.empty:
            return []

        # Convert DataFrame rows to Task objects
        tasks = [Task.from_df_row(row) for _, row in df.iterrows()]
        return tasks

    except Exception as e:
        core.logger.error(f"Error fetching tasks: {e}")
        return []


def on_task_checkbox_click(core: AppCore, task_id: int, checked: bool):
    """Handle task completion checkbox click (non-async wrapper)."""

    async def _update_task():
        try:
            await core.query_engine.function_db(
                "set_task_completion",
                task_id=task_id,
                completed=checked,
            )
            # Emit event to refresh tasks
            core.event_bus.emit("tasks_refresh_requested")
        except Exception as e:
            core.logger.error(f"Failed to update task completion: {e}")
            core.event_bus.notify(f"Error: {e}", type_="negative")

    asyncio.create_task(_update_task())


def on_task_edit_click(core: AppCore, task: Task, page_state: dict, refresh_callback):
    """Switch to Update view and select task."""

    async def _switch_to_update():
        try:
            task_identifier = f"{task.title} (ID: {task.task_id})"

            # Render update form in right panel
            page_state["form_container"].clear()

            with page_state["form_container"]:
                await render_update_form(core, page_state, refresh_callback)

            # Wait for task selector options to load (via ui.timer in render_update_form)
            await asyncio.sleep(0.2)

            # Set task selector value after form is rendered and options loaded
            if page_state.get("task_selector"):
                task_selector_widget = page_state["task_selector"]
                task_selector_widget.value = task_identifier
                task_selector_widget.widget.update()

                # Manually trigger child widget refresh since programmatic value changes
                # don't fire on_value_change events in NiceGUI
                if page_state.get("task_update_child_widgets"):
                    for field_name, widget in page_state[
                        "task_update_child_widgets"
                    ].items():
                        if widget and hasattr(widget, "_on_parent_change"):
                            widget._on_parent_change()

                # Emit event for manual dropdown refresh (status/priority)
                await asyncio.sleep(0.1)  # Small delay for UI to propagate
                core.event_bus.emit("task_selected", task_id=task.task_id)
        except Exception as e:
            core.logger.error(f"Error switching to update view: {e}")

    asyncio.create_task(_switch_to_update())


def on_task_click(core: AppCore, task: Task, page_state: dict):
    """Switch to View with read-only task display using YAML config."""

    async def _switch_to_view():
        try:
            view_config = core.tasks_config.get("task", {}).get("view", {})
            rows_config = view_config.get("rows", [])
            fields_config = {f["name"]: f for f in view_config.get("fields", [])}

            # Render view in right panel
            page_state["form_container"].clear()

            with page_state["form_container"]:
                with entity_card_shell(constrain_width=False):
                    with entity_card_header():
                        ui.label(task.title).classes("text-h6")

                    with entity_card_content():
                        with ui.column().classes("w-full gap-2"):
                            # Render rows from YAML config
                            for row_fields in rows_config:
                                if len(row_fields) == 1:
                                    # Single field row
                                    field_name = row_fields[0]
                                    field_config = fields_config.get(field_name, {})
                                    label = field_config.get("label", field_name)
                                    value = getattr(task, field_name, "N/A")

                                    # Format value based on field type
                                    if field_config.get("format") == "boolean":
                                        value = "Yes" if value else "No"
                                    elif value is None:
                                        value = "N/A"

                                    if field_config.get("multiline"):
                                        ui.textarea(
                                            label=label, value=str(value)
                                        ).props("readonly outlined").classes("w-full")
                                    else:
                                        ui.input(label=label, value=str(value)).props(
                                            "readonly outlined"
                                        ).classes("w-full")

                                else:
                                    # Multi-field row with readonly inputs
                                    with ui.row().classes("w-full gap-2"):
                                        for field_name in row_fields:
                                            field_config = fields_config.get(
                                                field_name, {}
                                            )
                                            label = field_config.get(
                                                "label", field_name
                                            )
                                            value = getattr(task, field_name, "N/A")

                                            # Format value based on field type
                                            if field_config.get("format") == "boolean":
                                                value = "Yes" if value else "No"
                                            elif value is None:
                                                value = "N/A"

                                            # Use readonly input for bordered appearance
                                            ui.input(
                                                label=label, value=str(value)
                                            ).props("readonly outlined").classes(
                                                "flex-1 min-w-0"
                                            )
        except Exception as e:
            core.logger.error(f"Error displaying task details: {e}")

    asyncio.create_task(_switch_to_view())


def render_card_view(
    core: AppCore,
    tasks: list[Task],
    container: ui.element,
    page_state: dict,
    refresh_callback,
):
    """Render tasks in card view."""
    container.clear()

    if not tasks:
        with container:
            ui.label("No tasks found").classes(
                UI_STYLES.get_layout_classes("text_center_muted_padded")
            )
        return

    with container:
        with (
            ui.scroll_area()
            .classes(UI_STYLES.get_layout_classes("full_width"))
            .style("height: 100%; min-width: 0;")
        ):
            with (
                ui.element()
                .classes("w-full")
                .style(
                    "display: grid; "
                    "grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); "
                    "gap: 16px; "
                    "padding: 0px;"
                )
            ):
                for task in tasks:

                    def make_checkbox_handler(tid, c):
                        return lambda _task_id, checked: on_task_checkbox_click(
                            c, tid, checked
                        )

                    def make_edit_handler(t, c, ps, cb):
                        return lambda _: on_task_edit_click(c, t, ps, cb)

                    def make_click_handler(t, c, ps):
                        return lambda _: on_task_click(c, t, ps)

                    helpers.create_task_card(
                        task_id=str(task.task_id),
                        columns=task.to_columns_format(),
                        completed=task.completed,
                        on_checkbox_click=make_checkbox_handler(task.task_id, core),
                        on_edit_click=make_edit_handler(
                            task, core, page_state, refresh_callback
                        ),
                        on_card_click=make_click_handler(task, core, page_state),
                        config_task_visuals=core.task_visuals,
                    )


def render_table_view(
    core: AppCore,
    tasks: list[Task],
    container: ui.element,
    page_state: dict,
    refresh_callback,
):
    """Render tasks in table view using YAML config."""
    container.clear()

    if not tasks:
        with container:
            ui.label("No tasks found").classes("text-gray-500 text-center w-full p-8")
        return

    task_lookup = {str(task.task_id): task for task in tasks}

    # Load column configuration from YAML
    table_config = core.tasks_config.get("task", {}).get("table", {})
    column_configs = table_config.get("columns", [])

    table_data = [task.to_dict() for task in tasks]

    # Build columns array from YAML config
    columns = []
    for col_config in column_configs:
        col_name = col_config.get("name")
        # Map "selected" field name to "completed" (our actual data field)
        field_name = (
            "completed" if col_name == "selected" else col_config.get("field", col_name)
        )

        column_def = {
            "name": col_name,
            "label": col_config.get("label", ""),
            "field": field_name,
            "align": col_config.get("align", "left"),
            "sortable": col_config.get("sortable", True),
        }
        columns.append(column_def)

    with container:
        with (
            ui.scroll_area()
            .classes(UI_STYLES.get_layout_classes("full_width"))
            .style("height: 100%; min-width: 0;")
        ):
            table = (
                ui.table(
                    columns=columns,
                    rows=table_data,
                    row_key="task_id",
                )
                .classes("w-full")
                .props("flat")
            )

        # Custom cell rendering for checkbox
        table.add_slot(
            "body-cell-selected",
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

        # Custom cell rendering for actions (edit button)
        table.add_slot(
            "body-cell-actions",
            """
            <q-td :props="props" @click.stop>
                <q-btn flat dense round icon="edit" size="sm"
                    @click="$parent.$emit('edit-click', props.row.task_id)" />
            </q-td>
        """,
        )

        # Wire up event handlers
        table.on(
            "checkbox-click",
            lambda e: on_task_checkbox_click(core, e.args[0], e.args[1]),
        )

        # Row click → switch to view panel
        def handle_row_click(e):
            row = (
                e.args[1]
                if isinstance(e.args, (list, tuple)) and len(e.args) > 1
                else e.args
            )
            task_id = str(row.get("task_id", ""))
            task = task_lookup.get(task_id)
            if task:
                on_task_click(core, task, page_state)

        table.on("row-click", handle_row_click)

        # Edit button click → switch to update panel and pre-select task
        def handle_edit_click(e):
            task_id = str(e.args)
            task = task_lookup.get(task_id)
            if task:
                on_task_edit_click(core, task, page_state, refresh_callback)

        table.on("edit-click", handle_edit_click)


# ============================================================================
#  Main Task Page Entry Point
# ============================================================================


async def tasks_page():
    """
    Tasks page - for managing tasks/todos.

    Note: No @ui.page decorator - accessed via SPA sub_pages in root.py
    Direct access to /tasks is handled by redirect in root.py
    """

    core = await AppCore.get_or_initialize()
    setup_debug_keyboard_handlers(core)

    # Local state for this page instance
    page_state = {
        "view_is_cards": True,
        "sort_select": None,
        "show_completed_toggle": None,
        "tasks_container": None,
        "current_view": "list",  # list, add, update, view
        "task_selector": None,
        "view_container": None,
        "form_container": None,
    }

    async def switch_to_view_and_refresh():
        """Clear form panel and refresh task list."""
        page_state["current_view"] = "list"
        page_state["form_container"].clear()
        # Refresh task list after form submission
        await refresh_tasks()

    # Create a callable that references the async function properly
    def refresh_view_and_tasks():
        return asyncio.create_task(switch_to_view_and_refresh())

    async def refresh_tasks():
        """Refresh task display."""
        if not page_state["tasks_container"]:
            core.logger.warning("Tasks container not found for refresh")
            return

        sort_by = (
            page_state["sort_select"].value
            if page_state["sort_select"]
            else "Due Date (Earliest First)"
        )
        show_completed = (
            page_state["show_completed_toggle"].value
            if page_state["show_completed_toggle"]
            else False
        )
        tasks = await fetch_tasks(core, sort_by, show_completed)

        if page_state["view_is_cards"]:
            render_card_view(
                core,
                tasks,
                page_state["tasks_container"],
                page_state,
                refresh_view_and_tasks,
            )
        else:
            render_table_view(
                core,
                tasks,
                page_state["tasks_container"],
                page_state,
                refresh_view_and_tasks,
            )

    async def toggle_view():
        """Toggle between card and table view."""
        page_state["view_is_cards"] = not page_state["view_is_cards"]
        await refresh_tasks()

    def switch_to_view(view_name: str):
        """Switch between add/update/view modes in right panel."""
        page_state["current_view"] = view_name

        async def _render_view():
            """Async function to render view with proper UI context."""
            page_state["form_container"].clear()
            with page_state["form_container"]:
                if view_name == "add":
                    await render_add_form(core, refresh_view_and_tasks)
                elif view_name == "update":
                    await render_update_form(core, page_state, refresh_view_and_tasks)
                elif view_name == "view":
                    with entity_card_shell(constrain_width=False):
                        with entity_card_header():
                            ui.label("Task Details").classes("text-h6")
                        with entity_card_content():
                            page_state["view_container"] = ui.column().classes("w-full")
                            with page_state["view_container"]:
                                ui.label("Click a task card to view details").classes(
                                    "text-gray-500"
                                )

        asyncio.create_task(_render_view())

    def handle_refresh_event():
        asyncio.create_task(refresh_tasks())

    core.event_bus.register("tasks_refresh_requested", handle_refresh_event)

    # ========================================================================
    # Main UI Layout
    # ========================================================================

    # ========================================================================
    # Toolbar Controls
    # ========================================================================

    def render_toolbar():
        """Render control panel - stable across data refreshes."""
        with toolbar(core.theme):
            with toolbar_group(core.theme, "Sort", divider_after=True):
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
                page_state["sort_select"] = ui.select(
                    options=sort_options,
                    value="Due Date (Earliest First)",
                    on_change=lambda: refresh_tasks(),
                ).classes(SORT_SELECT_WIDTH)

            with toolbar_group(core.theme, "Show Completed", divider_after=True):
                page_state["show_completed_toggle"] = ui.switch(
                    value=False,
                    on_change=lambda: refresh_tasks(),
                )

            with toolbar_group(core.theme, "Display", divider_after=False):
                view_toggle_btn = ui.button(
                    icon="view_module",
                    on_click=toggle_view,
                ).props("flat dense")
                view_toggle_btn.tooltip("Toggle Card/Table View")

            ui.space()
            with toolbar_group(core.theme, "Tasks", divider_after=False):
                add_btn = ui.button(
                    "Add",
                    icon="add",
                    on_click=lambda: switch_to_view("add"),
                ).props("flat dense")
                add_btn.tooltip("Add New Task")

                update_btn = ui.button(
                    "Update",
                    icon="edit",
                    on_click=lambda: switch_to_view("update"),
                ).props("flat dense")
                update_btn.tooltip("Update Task")

                view_btn = ui.button(
                    "View",
                    icon="visibility",
                    on_click=lambda: switch_to_view("view"),
                ).props("flat dense")
                view_btn.tooltip("View Task Details")

    render_toolbar()

    with (
        ui.splitter(value=SPLITTER_RATIO)
        .classes("w-full")
        .style("height: calc(100vh - 160px);") as splitter
    ):
        # Left panel: Task list
        with splitter.before:
            with ui.column().classes("w-full h-full"):
                # Tasks container
                page_state["tasks_container"] = (
                    ui.column()
                    .classes(UI_STYLES.get_layout_classes("full_width"))
                    .style("height: 100%;")
                )

                # Defer initial task loading to avoid sync/async issues
                ui.timer(0.1, refresh_tasks, once=True)

        # Right panel: Forms
        with splitter.after:
            with ui.scroll_area().classes("w-full h-full"):
                page_state["form_container"] = ui.column().classes("p-4 w-full pb-8")
                # Forms will be rendered here dynamically when buttons are clicked


# ============================================================================
# Form Rendering Functions
# ============================================================================


async def render_add_form(core: AppCore, refresh_callback):
    """Render the Add Task form"""

    submit_button = None

    with entity_card_shell(constrain_width=False):
        with entity_card_header():
            with ui.element("div").style(
                "display:flex; align-items:center; gap:0.25rem; overflow:hidden;"
            ):
                ui.label("Add New Task").classes("text-h6")
                ui.space()
                submit_button = ui.button(icon="add").props("color=primary disabled")

        with entity_card_content():
            data = await get_customer_project_data(core)

            # Debug logging with notification ## TODO remove after verification
            customer_count = len(data.get("customer_data", []))
            core.logger.info(
                f"Task form: Customer data loaded: {customer_count} customers"
            )
            if data.get("customer_data"):
                core.logger.info(f"First customer: {data['customer_data'][0]}")
            else:
                core.logger.warning("No customer data found for add form")

            # Data fetcher for dynamic widgets
            async def data_fetcher(source_key, parent_val=None):
                if parent_val and source_key == "project_names":
                    # Return projects for selected customer
                    return data.get("project_names", {}).get(parent_val, [])
                elif source_key == "customer_data":
                    return data.get("customer_data", [])
                return []

            # Get form config for layout
            form_config = core.tasks_config.get("task", {}).get("add", {})
            rows_layout = form_config.get("rows", [])
            fields_config = form_config.get("fields", [])

            # Create field lookup
            field_map = {f["name"]: f for f in fields_config}

            # Widget storage for form submission
            form_widgets = {}
            parent_map = {}

            with ui.column().classes("w-full gap-2"):
                # Render fields according to YAML layout - ADD TAB
                for row in rows_layout:
                    if len(row) == 1:
                        # Single field - add directly to column for full width
                        field_name = row[0]
                        field_config = field_map.get(field_name, {})

                        # Create widget based on field name
                        if field_name == "title":
                            title = DynamicInput(
                                name="title",
                                label="Task Title",
                                field_config={},
                            )
                            title.widget.classes("w-full").props("required")
                            form_widgets["title"] = title

                        elif field_name == "description":
                            description = DynamicTextArea(
                                name="description",
                                label="Description",
                                field_config={},
                            )
                            description.widget.classes("w-full")
                            form_widgets["description"] = description

                        elif field_name == "tags":
                            tags = DynamicInput(
                                name="tags",
                                label="Tags (comma-separated)",
                                field_config={},
                            )
                            tags.widget.classes("w-full")
                            form_widgets["tags"] = tags
                    else:
                        # Multi-field row - use ui.row() with flex-1 widgets
                        with ui.row().classes("w-full gap-2"):
                            for field_name in row:
                                field_config = field_map.get(field_name, {})

                                # Create widget based on field name
                                if field_name == "customer_name":
                                    customer_select = DynamicDropDown(
                                        name="customer",
                                        label="Customer",
                                        data_fetcher=data_fetcher,
                                        options_source="customer_data",
                                        field_config={
                                            "with_input": True,
                                            "options": data["customer_data"],
                                        },
                                    )
                                    customer_select.widget.classes("flex-1 min-w-0")
                                    form_widgets["customer_name"] = customer_select
                                    parent_map["customer_name"] = customer_select

                                    # Trigger initial load via ui.timer
                                    async def init_customer_options():
                                        customer_select.widget.options = data[
                                            "customer_data"
                                        ]
                                        customer_select.widget.update()
                                        core.logger.info(
                                            f"Customer dropdown initialized with {len(data['customer_data'])} options"
                                        )

                                    ui.timer(0.1, init_customer_options, once=True)

                                elif field_name == "project_name":
                                    project_select = DynamicDropDown(
                                        name="project",
                                        data_fetcher=data_fetcher,
                                        options_source="project_names",
                                        parent=customer_select,
                                        label="Project",
                                        field_config={"with_input": True},
                                    )
                                    project_select.widget.classes("flex-1 min-w-0")
                                    form_widgets["project_name"] = project_select

                                elif field_name == "status":
                                    status = DynamicDropDown(
                                        name="status",
                                        label="Status",
                                        field_config={
                                            "options": field_config.get("options", []),
                                            "with_input": False,
                                        },
                                        initial_value=field_config.get(
                                            "default", "To Do"
                                        ),
                                    )
                                    status.widget.classes("flex-1 min-w-0")
                                    form_widgets["status"] = status

                                elif field_name == "priority":
                                    priority = DynamicDropDown(
                                        name="priority",
                                        label="Priority",
                                        field_config={
                                            "options": field_config.get("options", []),
                                            "with_input": False,
                                        },
                                        initial_value=field_config.get(
                                            "default", "Medium"
                                        ),
                                    )
                                    priority.widget.classes("flex-1 min-w-0")
                                    form_widgets["priority"] = priority

                                elif field_name == "assigned_to":
                                    assigned_to = DynamicInput(
                                        name="assigned_to",
                                        label="Assigned To",
                                        field_config={},
                                    )
                                    assigned_to.widget.classes("flex-1 min-w-0")
                                    form_widgets["assigned_to"] = assigned_to

                                elif field_name == "due_date":
                                    default_due = (
                                        datetime.now() + timedelta(days=1)
                                    ).strftime("%Y-%m-%d")
                                    due_date = DynamicDateInput(
                                        name="due_date",
                                        label="Due Date",
                                        field_config={"default": default_due},
                                    )
                                    due_date.widget.classes("flex-1 min-w-0")
                                    form_widgets["due_date"] = due_date

                                elif field_name == "estimated_hours":
                                    estimated_hours = DynamicNumber(
                                        name="estimated_hours",
                                        label="Estimated Hours",
                                        field_config={"min": 0, "step": 0.5},
                                        initial_value=0,
                                    )
                                    estimated_hours.widget.classes("flex-1 min-w-0")
                                    form_widgets["estimated_hours"] = estimated_hours

            async def handle_submit():
                try:
                    values = {name: w.get_value() for name, w in form_widgets.items()}
                    success = await core.function_db.create(
                        entity_type="task",
                        values=values,
                        functions=core.tasks_functions,
                    )
                    if success:
                        ui.notify("Task created", type="positive")
                        if inspect.iscoroutinefunction(refresh_callback):
                            await refresh_callback()
                        else:
                            refresh_callback()
                    else:
                        ui.notify("Failed to create task", type="negative")
                except Exception as e:
                    core.logger.error(f"Error creating task: {e}")
                    ui.notify(f"Error: {e}", type="negative")

            submit_button.on("click", handle_submit)
            submit_button.props(remove="disabled")


async def render_update_form(core: AppCore, page_state: dict, refresh_callback):
    """Render the Update Task form"""
    update_button = None

    with entity_card_shell(constrain_width=False):
        with entity_card_header():
            with ui.element("div").style(
                "display:flex; align-items:center; gap:0.25rem; overflow:hidden;"
            ):
                ui.label("Update Task").classes("text-h6")
                ui.space()
                update_button = ui.button(icon="save").props("color=primary disabled")

        with entity_card_content():
            form_widgets = {}

            async def task_data_fetcher(field_name, task_selector_value):
                """Fetch task field value when task is selected."""
                import re

                if not task_selector_value:
                    return None

                match = re.search(r"\(ID: (\d+)\)", str(task_selector_value))
                if not match:
                    return None

                task_id = int(match.group(1))
                task_df = await core.query_engine.query_db(
                    f"SELECT * FROM tasks WHERE task_id = {task_id}"
                )

                if task_df is not None and not task_df.empty:
                    task_data = task_df.iloc[0]
                    return task_data.get(field_name, "")
                return None

            # Custom refresh handler for dropdowns with fixed options (status, priority)
            async def refresh_dropdown_value(widget, field_name, task_selector_value):
                """Set dropdown value without refreshing options."""
                value = await task_data_fetcher(field_name, task_selector_value)
                core.logger.info(f"Refreshing {field_name}: {value}")
                if value is not None and value != "":
                    widget.value = value
                    widget.update()
                else:
                    core.logger.warning(f"No value found for {field_name}")

            # Get form config for layout
            form_config = core.tasks_config.get("task", {}).get("update", {})
            rows_layout = form_config.get("rows", [])
            fields_config = form_config.get("fields", [])

            # Create field lookup
            field_map = {f["name"]: f for f in fields_config}

            # Define widget references (will be created in layout)
            task_selector = None
            title = None
            description = None
            status = None
            priority = None
            assigned_to = None
            due_date = None
            estimated_hours = None
            tags = None

            with ui.column().classes("w-full gap-2"):
                # Render fields according to YAML layout - UPDATE TAB
                for row in rows_layout:
                    if len(row) == 1:
                        # Single field - add directly to column for full width
                        field_name = row[0]
                        field_config = field_map.get(field_name, {})

                        if field_name == "task_selector":
                            task_selector = DynamicDropDown(
                                name="task_selector",
                                label="Select Task",
                                field_config={"options": [], "with_input": True},
                            )
                            task_selector.widget.classes("w-full")
                            page_state["task_selector"] = task_selector

                            # Load tasks
                            async def load_tasks():
                                tasks_df = await core.query_engine.query_db(
                                    "SELECT task_id, title FROM tasks ORDER BY title"
                                )
                                if tasks_df is not None and not tasks_df.empty:
                                    options = [
                                        f"{row['title']} (ID: {row['task_id']})"
                                        for _, row in tasks_df.iterrows()
                                    ]
                                    task_selector.options = options
                                    task_selector.update()

                            ui.timer(0.1, load_tasks, once=True)

                        elif field_name == "title":
                            title = DynamicInput(
                                name="title",
                                label="Title",
                                field_config={},
                                data_fetcher=task_data_fetcher,
                                options_source="title",
                                parent=task_selector,
                            )
                            title.widget.classes("w-full")

                        elif field_name == "description":
                            description = DynamicTextArea(
                                name="description",
                                label="Description",
                                field_config={},
                                data_fetcher=task_data_fetcher,
                                options_source="description",
                                parent=task_selector,
                            )
                            description.widget.classes("w-full")

                        elif field_name == "tags":
                            tags = DynamicInput(
                                name="tags",
                                label="Tags (comma-separated)",
                                field_config={},
                                data_fetcher=task_data_fetcher,
                                options_source="tags",
                                parent=task_selector,
                            )
                            tags.widget.classes("w-full")
                    else:
                        # Multi-field row - use ui.row() with flex-1 widgets
                        with ui.row().classes("w-full gap-2"):
                            for field_name in row:
                                field_config = field_map.get(field_name, {})

                                if field_name == "status":
                                    status = DynamicDropDown(
                                        name="status",
                                        label="Status",
                                        field_config={
                                            "options": field_config.get("options", []),
                                            "with_input": False,
                                        },
                                    )
                                    status.widget.classes("flex-1 min-w-0")
                                    form_widgets["status"] = status.widget

                                elif field_name == "priority":
                                    priority = DynamicDropDown(
                                        name="priority",
                                        label="Priority",
                                        field_config={
                                            "options": field_config.get("options", []),
                                            "with_input": False,
                                        },
                                    )
                                    priority.widget.classes("flex-1 min-w-0")
                                    form_widgets["priority"] = priority.widget

                                elif field_name == "assigned_to":
                                    assigned_to = DynamicInput(
                                        name="assigned_to",
                                        label="Assigned To",
                                        field_config={},
                                        data_fetcher=task_data_fetcher,
                                        options_source="assigned_to",
                                        parent=task_selector,
                                    )
                                    assigned_to.widget.classes("flex-1 min-w-0")

                                elif field_name == "due_date":
                                    due_date = DynamicDateInput(
                                        name="due_date",
                                        label="Due Date",
                                        field_config={},
                                        data_fetcher=task_data_fetcher,
                                        options_source="due_date",
                                        parent=task_selector,
                                    )
                                    due_date.widget.classes("flex-1 min-w-0")

                                elif field_name == "estimated_hours":
                                    estimated_hours = DynamicNumber(
                                        name="estimated_hours",
                                        label="Estimated Hours",
                                        field_config={"min": 0, "step": 0.5},
                                        data_fetcher=task_data_fetcher,
                                        options_source="estimated_hours",
                                        parent=task_selector,
                                    )
                                    estimated_hours.widget.classes("flex-1 min-w-0")

            # Store child widget references in page_state for external refresh triggers
            page_state["task_update_child_widgets"] = {
                "title": title,
                "description": description,
                "assigned_to": assigned_to,
                "due_date": due_date,
                "estimated_hours": estimated_hours,
                "tags": tags,
            }

            # Manual refresh for dropdowns when task is selected
            async def on_task_change(e=None):
                """Manually refresh dropdown values when task changes."""
                if task_selector and task_selector.value:
                    await refresh_dropdown_value(
                        form_widgets["status"], "status", task_selector.value
                    )
                    await refresh_dropdown_value(
                        form_widgets["priority"], "priority", task_selector.value
                    )

            # Wire up task selector change event using on_value_change for programmatic changes
            if task_selector:
                task_selector.widget.on_value_change(
                    lambda e: asyncio.create_task(on_task_change(e))
                )

            # Also listen for task_selected event (from edit button clicks)
            def handle_task_selected_event(**kwargs):
                """Handle task selection from edit button."""
                asyncio.create_task(on_task_change())

            core.event_bus.register("task_selected", handle_task_selected_event)

            # Update button (outside column, at entity_card_content level)
            async def handle_update():
                import re

                if not task_selector or not task_selector.value:
                    ui.notify("Please select a task", type="warning")
                    return

                match = re.search(r"\(ID: (\d+)\)", str(task_selector.value))
                if not match:
                    return

                task_id = int(match.group(1))

                try:
                    # Update via database function
                    success, message = await core.query_engine.function_db(
                        "update_task",
                        task_id=task_id,
                        title=title.value,
                        description=description.value,
                        status=status.value,
                        priority=priority.value,
                        assigned_to=assigned_to.value,
                        due_date=due_date.value if due_date.value else None,
                        estimated_hours=estimated_hours.value,
                        tags=tags.value,
                    )

                    if success:
                        ui.notify("Task updated successfully!", type="positive")
                        # Refresh task list and return to list view
                        if inspect.iscoroutinefunction(refresh_callback):
                            await refresh_callback()
                        else:
                            refresh_callback()
                        await load_tasks()  # Refresh task list
                    else:
                        ui.notify("Failed to update task", type="negative")
                except Exception as e:
                    core.logger.error(f"Error updating task: {e}")
                    ui.notify(f"Error: {e}", type="negative")

            # Connect button to handler and enable it
            update_button.on("click", handle_update)
            update_button.props(remove="disabled")
