"""
Task Management Page

Task management interface with card/table views and CRUD operations.
Uses V2 architecture with per-client AppCore and event-driven updates.
Fully config-driven using the 'task' section in config_ui.yml.
"""

import asyncio
import inspect
from dataclasses import dataclass
from typing import Optional
import re

from nicegui import ui

from ..core.app import AppCore
from .. import helpers
from ..helpers import UI_STYLES
from ..ui.keyboard_handlers import setup_debug_keyboard_handlers
from ..ui.dynamic_widgets import WIDGET_CLASSES, DynamicDropDown

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

        def safe_float(val, default=0.0):
            try:
                return float(val) if val not in (None, "", "None") else default
            except (ValueError, TypeError):
                return default

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
            estimated_hours=safe_float(row.get("estimated_hours")),
            actual_hours=safe_float(row.get("actual_hours")),
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


def extract_task_id(selector_value: str) -> int | None:
    """Extract task ID from selector string like 'My Task (ID: 42)'."""
    match = re.search(r"\(ID: (\d+)\)", str(selector_value))
    return int(match.group(1)) if match else None


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
    sort_queries = {
        "Due Date (Earliest First)": "ORDER BY CASE WHEN due_date IS NULL THEN 1 ELSE 0 END DESC, due_date ASC",
        "Due Date (Latest First)": "ORDER BY CASE WHEN due_date IS NULL THEN 0 ELSE 1 END DESC, due_date DESC",
        "Priority (High to Low)": """ORDER BY CASE priority 
            WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 
            WHEN 'Medium' THEN 3 WHEN 'Low' THEN 4 ELSE 5 END ASC""",
        "Priority (Low to High)": """ORDER BY CASE priority 
            WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 
            WHEN 'Medium' THEN 3 WHEN 'Low' THEN 4 ELSE 5 END DESC""",
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
            ui.label("No tasks found").classes(UI_STYLES.get_layout_classes("text_center_muted_padded"))
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

    async def refresh_and_clear_form():
        page_state["current_view"] = "list"
        page_state["form_container"].clear()
        await refresh_tasks()

    # Wrap for sync contexts
    def refresh_callback():
        asyncio.create_task(refresh_and_clear_form())

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
                refresh_callback,
            )
        else:
            render_table_view(
                core,
                tasks,
                page_state["tasks_container"],
                page_state,
                refresh_callback,
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
                    await render_add_form(core, refresh_callback)
                elif view_name == "update":
                    await render_update_form(core, page_state, refresh_callback)
                elif view_name == "view":
                    with entity_card_shell(constrain_width=False):
                        with entity_card_header():
                            ui.label("Task Details").classes("text-h6")
                        with entity_card_content():
                            page_state["view_container"] = ui.column().classes("w-full")
                            with page_state["view_container"]:
                                ui.label("Click a task card to view details").classes(
                                    UI_STYLES.get_layout_classes("text_muted")
                                )

        asyncio.create_task(_render_view())

    def handle_refresh_event():
        asyncio.create_task(refresh_tasks())

    if page_state.get("_refresh_handler"):
        core.event_bus.unregister(
            "tasks_refresh_requested", page_state["_refresh_handler"]
        )

    page_state["_refresh_handler"] = handle_refresh_event
    core.event_bus.register("tasks_refresh_requested", handle_refresh_event)

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
                asyncio.create_task(refresh_tasks())

        # Right panel: Forms
        with splitter.after:
            with ui.scroll_area().classes("w-full h-full"):
                page_state["form_container"] = ui.column().classes("p-4 w-full pb-8")
                # Forms will be rendered here dynamically when buttons are clicked


# ============================================================================
# Form Rendering Functions
# ============================================================================


def build_form_widgets(
    rows_layout: list,
    field_map: dict,
    data_fetcher,
    page_state: dict = None,
    main_param: str = None,
) -> dict:
    """Dynamically build form widgets from YAML layout config."""
    form_widgets = {}

    with ui.column().classes("w-full gap-2"):
        for row in rows_layout:
            is_single = len(row) == 1
            css_class = "w-full" if is_single else "flex-1 min-w-0"
            container = (
                ui.column().classes("w-full")
                if is_single
                else ui.row().classes("w-full gap-2")
            )

            with container:
                for field_name in row:
                    field_config = field_map.get(field_name, {})
                    widget_class = WIDGET_CLASSES.get(field_config.get("type"))

                    if not widget_class:
                        print(f"Unknown widget type for field '{field_name}'")
                        continue

                    parent_name = field_config.get("parent")
                    parent_widget = (
                        form_widgets.get(parent_name) if parent_name else None
                    )
                    initial_options = field_config.get("options", [])

                    widget = widget_class(
                        name=field_name,
                        label=field_config.get("label", field_name),
                        field_config={
                            "options": initial_options,
                            "with_input": field_config.get("with_input", False),
                            "min": field_config.get("min", 0),
                            "step": field_config.get("step", 1),
                        },
                        data_fetcher=data_fetcher if parent_widget else None,
                        options_source=field_config.get("options_source", field_name),
                        parent=parent_widget,
                        initial_value=field_config.get("default"),
                    )
                    widget.widget.classes(css_class)
                    form_widgets[field_name] = widget

                    # Store main param widget in page_state (e.g. task_selector)
                    if page_state is not None and field_name == main_param:
                        page_state[main_param] = widget

                    # Async load for dynamic options (no predefined options, no parent)
                    options_source = field_config.get("options_source")
                    if options_source == "task_list":

                        async def load_task_list(w=widget):
                            opts = await data_fetcher("task_list", None)
                            if opts:
                                w.options = opts
                                w.widget.update()

                        asyncio.create_task(load_task_list())
                    elif options_source and not initial_options and not parent_widget:

                        async def load_options(w=widget, src=options_source):
                            opts = await data_fetcher(src, None)
                            if opts:
                                w.options = opts
                                w.widget.update()

                        asyncio.create_task(load_options())

    return form_widgets


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

            async def data_fetcher(source_key, parent_val=None):
                if parent_val and source_key == "project_names":
                    return data.get("project_names", {}).get(parent_val, [])
                elif source_key == "customer_data":
                    return data.get("customer_data", [])
                return []

            form_config = core.tasks_config.get("task", {}).get("add", {})
            rows_layout = form_config.get("rows", [])
            field_map = {f["name"]: f for f in form_config.get("fields", [])}

            form_widgets = build_form_widgets(
                rows_layout=rows_layout,
                field_map=field_map,
                data_fetcher=data_fetcher,
            )

            async def handle_submit():
                try:
                    values = {name: w.value for name, w in form_widgets.items()}
                    success = await core.query_engine.function_db(
                        "insert_task",
                        **values,
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

            async def task_data_fetcher(field_name, task_selector_value):
                if field_name == "task_list":
                    tasks_df = await core.query_engine.query_db(
                        "SELECT task_id, title FROM tasks ORDER BY title"
                    )
                    if tasks_df is not None and not tasks_df.empty:
                        return [
                            f"{r['title']} (ID: {r['task_id']})"
                            for _, r in tasks_df.iterrows()
                        ]
                    return []

                if not task_selector_value:
                    return None
                match = extract_task_id(task_selector_value)
                if not match:
                    return None

                task_df = await core.query_engine.query_db(
                    "SELECT * FROM tasks WHERE task_id = ?", params=(match,)
                )
                if task_df is not None and not task_df.empty:
                    return task_df.iloc[0].get(field_name, "")
                return None

            async def refresh_field_value(widget, field_name, selector_value):
                value = await task_data_fetcher(field_name, selector_value)
                core.logger.info(f"Refreshing {field_name}: {value!r}")
                if value is None or value == "":
                    core.logger.warning(f"No value found for {field_name}")
                    return
                if isinstance(widget, DynamicDropDown) and widget.widget.options:
                    widget.widget.value = value
                    widget.widget.update()
                else:
                    widget.widget.set_value(value)

            form_config = core.tasks_config.get("task", {}).get("update", {})
            rows_layout = form_config.get("rows", [])
            field_map = {f["name"]: f for f in form_config.get("fields", [])}
            main_param = form_config.get("action", {}).get(
                "main_param", "task_selector"
            )

            form_widgets = build_form_widgets(
                rows_layout=rows_layout,
                field_map=field_map,
                data_fetcher=task_data_fetcher,
                page_state=page_state,
                main_param=main_param,
            )

            page_state["task_update_child_widgets"] = {
                name: w for name, w in form_widgets.items() if name != main_param
            }

            async def on_task_change(e=None):
                if page_state.get("_refreshing"):
                    return
                page_state["_refreshing"] = True
                try:
                    selector = form_widgets.get(main_param)
                    if not selector or not selector.value:
                        return
                    for field_name, field_cfg in field_map.items():
                        if (
                            field_cfg.get("parent_update")
                            and field_name in form_widgets
                        ):
                            await refresh_field_value(
                                form_widgets[field_name], field_name, selector.value
                            )
                finally:
                    page_state["_refreshing"] = False

            task_selector_widget = form_widgets.get(main_param)
            if task_selector_widget:
                task_selector_widget.widget.on_value_change(
                    lambda e: asyncio.create_task(on_task_change(e))
                )

            def handle_task_selected_event(**kwargs):
                asyncio.create_task(on_task_change())

            if page_state.get("_task_selected_handler"):
                core.event_bus.unregister(
                    "task_selected", page_state["_task_selected_handler"]
                )

            page_state["_task_selected_handler"] = handle_task_selected_event
            core.event_bus.register("task_selected", handle_task_selected_event)

            async def handle_update():
                selector = form_widgets.get(main_param)
                if not selector or not selector.value:
                    ui.notify("Please select a task", type="warning")
                    return
                task_id = extract_task_id(selector.value)
                if not task_id:
                    return
                try:
                    kwargs = {
                        name: w.value
                        for name, w in form_widgets.items()
                        if name != main_param
                    }
                    success, _ = await core.query_engine.function_db(
                        "update_task", task_id=task_id, **kwargs
                    )
                    if success:
                        ui.notify("Task updated successfully!", type="positive")
                        if inspect.iscoroutinefunction(refresh_callback):
                            await refresh_callback()
                        else:
                            refresh_callback()
                    else:
                        ui.notify("Failed to update task", type="negative")
                except Exception as e:
                    core.logger.error(f"Error updating task: {e}")
                    ui.notify(f"Error: {e}", type="negative")

            update_button.on("click", handle_update)
            update_button.props(remove="disabled")
