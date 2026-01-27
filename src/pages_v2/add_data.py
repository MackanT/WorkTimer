"""
Add Data Page (V2)

Data input interface for creating new customers, projects, and tasks.
Uses V2 architecture with per-client AppCore and event-driven updates.
"""

from nicegui import ui
from ..core.app import AppCore, get_config_loader
from ..helpers import UI_STYLES


async def add_data_page():
    """Add Data page - for creating new entities"""

    # Get or create AppCore for this client
    config_loader = get_config_loader()
    core = AppCore.get_or_create(config_loader)

    # Initialize engines if needed (first time only)
    if not core._initialized:
        await core.initialize_engines()

    # Main content
    with ui.column().classes("w-full p-4"):
        ui.label("Data Input").classes("text-h4 mb-4")

        # Get UI configuration for forms
        ui_config = core.config_loader.get_raw_dict("ui")

        # Create tabs for different entity types
        with ui.tabs() as tabs:
            tab_customer = ui.tab("Add Customer", icon="person_add")
            tab_project = ui.tab("Add Project", icon="folder_open")
            tab_task = ui.tab("Add Task", icon="add_task")
            tab_contact = ui.tab("Add Contact", icon="contacts")

        with ui.tab_panels(tabs, value=tab_customer).classes("w-full"):
            # Customer form
            with ui.tab_panel(tab_customer):
                await _render_customer_form(core, ui_config)

            # Project form
            with ui.tab_panel(tab_project):
                await _render_project_form(core, ui_config)

            # Task form
            with ui.tab_panel(tab_task):
                await _render_task_form(core, ui_config)

            # Contact form
            with ui.tab_panel(tab_contact):
                await _render_contact_form(core, ui_config)


async def _render_customer_form(core: AppCore, ui_config: dict):
    """Render the form for adding a new customer"""
    ui.label("Add New Customer").classes("text-h6 mb-2")

    # Get form configuration
    customer_config = ui_config.get("customer", {}).get("add", {})
    fields = customer_config.get("fields", [])

    # Create form inputs
    inputs = {}
    with ui.column().classes("gap-2 w-full max-w-2xl"):
        for field in fields:
            field_name = field.get("field")
            label = field.get("label", field_name)
            field_type = field.get("type", "text")

            if field_type == "text":
                inputs[field_name] = ui.input(label).classes("w-full")
            elif field_type == "select":
                # Handle dropdowns if needed
                inputs[field_name] = ui.input(label).classes("w-full")

        # Submit button
        async def submit_customer():
            try:
                # Get values
                values = {k: v.value for k, v in inputs.items()}

                # Use AddData service to create customer
                result = await core.add_data.add_customer(values)

                if result:
                    ui.notify("Customer added successfully!", type="positive")
                    # Clear form
                    for input_field in inputs.values():
                        input_field.value = ""
                else:
                    ui.notify("Failed to add customer", type="negative")
            except Exception as e:
                core.logger.error(f"Error adding customer: {e}")
                ui.notify(f"Error: {e}", type="negative")

        ui.button("Add Customer", icon="save", on_click=submit_customer).props(
            "color=primary"
        )


async def _render_project_form(core: AppCore, ui_config: dict):
    """Render the form for adding a new project"""
    ui.label("Add New Project").classes("text-h6 mb-2")

    # Get form configuration
    project_config = ui_config.get("project", {}).get("add", {})
    fields = project_config.get("fields", [])

    # Get customers for dropdown
    customers_df = await core.query_engine.get_customers()

    inputs = {}
    with ui.column().classes("gap-2 w-full max-w-2xl"):
        # Customer dropdown
        customer_options = {
            row["customer_id"]: row["customer_name"]
            for _, row in customers_df.iterrows()
        }
        inputs["customer_id"] = ui.select(
            label="Customer",
            options=customer_options,
            with_input=True,
        ).classes("w-full")

        # Other fields from config
        for field in fields:
            field_name = field.get("field")
            if field_name == "customer_id":
                continue  # Already added

            label = field.get("label", field_name)
            field_type = field.get("type", "text")

            if field_type == "text":
                inputs[field_name] = ui.input(label).classes("w-full")

        # Submit button
        async def submit_project():
            try:
                values = {}
                for k, v in inputs.items():
                    if hasattr(v, "value"):
                        values[k] = v.value

                result = await core.add_data.add_project(values)

                if result:
                    ui.notify("Project added successfully!", type="positive")
                    for input_field in inputs.values():
                        if hasattr(input_field, "value"):
                            input_field.value = (
                                "" if isinstance(input_field.value, str) else None
                            )
                else:
                    ui.notify("Failed to add project", type="negative")
            except Exception as e:
                core.logger.error(f"Error adding project: {e}")
                ui.notify(f"Error: {e}", type="negative")

        ui.button("Add Project", icon="save", on_click=submit_project).props(
            "color=primary"
        )


async def _render_task_form(core: AppCore, ui_config: dict):
    """Render the form for adding a new task"""
    ui.label("Add New Task").classes("text-h6 mb-2")

    # Get projects for dropdown
    projects_df = await core.query_engine.get_projects()

    inputs = {}
    with ui.column().classes("gap-2 w-full max-w-2xl"):
        # Project dropdown
        project_options = {
            row["project_id"]: f"{row['project_name']} ({row['customer_name']})"
            for _, row in projects_df.iterrows()
        }
        inputs["project_id"] = ui.select(
            label="Project",
            options=project_options,
            with_input=True,
        ).classes("w-full")

        # Task name
        inputs["task_name"] = ui.input("Task Name").classes("w-full")

        # Task description
        inputs["task_description"] = ui.textarea("Description").classes("w-full")

        # Submit button
        async def submit_task():
            try:
                values = {}
                for k, v in inputs.items():
                    if hasattr(v, "value"):
                        values[k] = v.value

                # Add task using AddData service
                result = await core.add_data.add_task(values)

                if result:
                    ui.notify("Task added successfully!", type="positive")
                    for input_field in inputs.values():
                        if hasattr(input_field, "value"):
                            input_field.value = (
                                "" if isinstance(input_field.value, str) else None
                            )
                else:
                    ui.notify("Failed to add task", type="negative")
            except Exception as e:
                core.logger.error(f"Error adding task: {e}")
                ui.notify(f"Error: {e}", type="negative")

        ui.button("Add Task", icon="save", on_click=submit_task).props("color=primary")


async def _render_contact_form(core: AppCore, ui_config: dict):
    """Render the form for adding a new contact"""
    ui.label("Add New Contact").classes("text-h6 mb-2")

    # Get customers for dropdown
    customers_df = await core.query_engine.get_customers()

    inputs = {}
    with ui.column().classes("gap-2 w-full max-w-2xl"):
        # Customer dropdown
        customer_options = {
            row["customer_id"]: row["customer_name"]
            for _, row in customers_df.iterrows()
        }
        inputs["customer_id"] = ui.select(
            label="Customer",
            options=customer_options,
            with_input=True,
        ).classes("w-full")

        # Contact fields
        inputs["contact_name"] = ui.input("Contact Name").classes("w-full")
        inputs["contact_email"] = ui.input("Email").classes("w-full")
        inputs["contact_phone"] = ui.input("Phone").classes("w-full")

        # Submit button
        async def submit_contact():
            try:
                values = {}
                for k, v in inputs.items():
                    if hasattr(v, "value"):
                        values[k] = v.value

                # You would add a method to AddData for this
                ui.notify(
                    "Contact add functionality not yet implemented", type="warning"
                )
                core.logger.info(f"Would add contact: {values}")

            except Exception as e:
                core.logger.error(f"Error adding contact: {e}")
                ui.notify(f"Error: {e}", type="negative")

        ui.button("Add Contact", icon="save", on_click=submit_contact).props(
            "color=primary"
        )
