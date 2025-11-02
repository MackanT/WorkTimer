"""
Add Data / Data Input UI Module

Handles all data input forms including:
- Customer management (add, update, disable, re-enable)
- Project management
- Bonus management
- DevOps work item creation and updates
- Database comparison tools
"""

import asyncio
import html
import os
import tempfile
from nicegui import events, ui

from ..globals import GlobalRegistry
from .. import helpers


def ui_add_data():
    """Main UI for adding and managing data entities."""
    # Get global instances from registry
    AD = GlobalRegistry.get("AD")
    DO = GlobalRegistry.get("DO")
    LOG = GlobalRegistry.get("LOG")
    QE = GlobalRegistry.get("QE")

    # Get configs from registry
    config_ui = GlobalRegistry.get("config_ui")
    config_devops_contacts = GlobalRegistry.get("config_devops_contacts")
    DEVOPS_TAGS = GlobalRegistry.get("DEVOPS_TAGS")
    MAIN_DB = GlobalRegistry.get("MAIN_DB")

    # Get UI_STYLES from helpers (it's a module-level instance)
    UI_STYLES = helpers.UI_STYLES

    # Import database class for generate_sync_sql method
    from ..database import Database

    asyncio.run(AD.refresh())

    # --- Data Preparation Functions (entity-specific logic) ---

    def prep_customer_data(tab_type, fields):
        """Prepare data sources for customer tabs."""
        active_data = helpers.filter_df(AD.df, {"c_current": 1})

        if tab_type == "Add":
            return {"date": None}

        elif tab_type == "Update":
            customer_names = helpers.get_unique_list(active_data, "customer_name")
            org_urls = {}
            pat_tokens = {}
            new_customer_names = {}

            for customer in customer_names:
                filtered = helpers.filter_df(AD.df, {"customer_name": customer})
                org_urls[customer] = helpers.get_unique_list(filtered, "org_url")
                pat_tokens[customer] = helpers.get_unique_list(filtered, "pat_token")
                new_customer_names[customer] = [customer]

            return {
                "customer_data": customer_names,
                "new_customer_name": new_customer_names,
                "org_url": org_urls,
                "pat_token": pat_tokens,
            }

        elif tab_type == "Disable":
            customer_names = helpers.get_unique_list(active_data, "customer_name")
            return {"customer_data": customer_names}

        elif tab_type == "Reenable":
            customer_names = helpers.get_unique_list(active_data, "customer_name")
            candidate_names = helpers.filter_df(
                AD.df,
                {"c_current": 0},
                return_as="distinct_list",
                column="customer_name",
            )
            reenable_names = sorted(list(set(candidate_names) - set(customer_names)))
            return {"customer_data": reenable_names}

        return {}

    def prep_project_data(tab_type, fields):
        """Prepare data sources for project tabs."""
        active_data = helpers.filter_df(AD.df, {"c_current": 1})
        active_customer_names = helpers.get_unique_list(active_data, "customer_name")

        if tab_type == "Add":
            return {"customer_data": active_customer_names}

        elif tab_type == "Update":
            project_names = {}
            new_project_name = {}
            new_git_id = {}

            for customer in active_customer_names:
                filtered = helpers.filter_df(
                    active_data, {"customer_name": customer, "p_current": 1}
                )
                project_names[customer] = helpers.get_unique_list(
                    filtered, "project_name"
                )
                for project in project_names[customer]:
                    filtered_cust = helpers.filter_df(
                        filtered, {"project_name": project}
                    )
                    new_project_name[project] = [project]
                    new_git_id[project] = helpers.get_unique_list(
                        filtered_cust, "git_id"
                    )

            return {
                "customer_data": active_customer_names,
                "project_names": project_names,
                "new_project_name": new_project_name,
                "new_git_id": new_git_id,
            }

        elif tab_type == "Disable":
            project_names = {}
            for customer in active_customer_names:
                filtered = helpers.filter_df(
                    active_data, {"customer_name": customer, "p_current": 1}
                )
                project_names[customer] = helpers.get_unique_list(
                    filtered, "project_name"
                )

            return {
                "customer_data": active_customer_names,
                "project_names": project_names,
            }

        elif tab_type == "Reenable":
            project_names = {}
            for customer in active_customer_names:
                filtered = helpers.filter_df(
                    active_data, {"customer_name": customer, "p_current": 0}
                )
                project_names[customer] = helpers.get_unique_list(
                    filtered, "project_name"
                )

            return {
                "customer_data": active_customer_names,
                "project_names": project_names,
            }

        return {}

    def prep_bonus_data(tab_type, fields):
        """Prepare data sources for bonus tabs."""
        # Bonus tab only has "Add" and doesn't need any dynamic data sources
        return {}

    def prep_devops_data(tab_type, fields):
        """Prepare data sources for DevOps Work Items tabs."""
        if DO.df is None:
            return {}

        customer_names = helpers.get_unique_list(DO.df, "customer_name")
        work_items = {}
        parent_names = {}

        for customer in customer_names:
            filtered = helpers.filter_df(DO.df, {"customer_name": customer})
            work_items[customer] = [
                row["display_name"] for _, row in filtered.iterrows()
            ]

            # Get parent items for different work item types
            epics_filtered = helpers.filter_df(
                DO.df, {"customer_name": customer, "type": "Epic"}
            )
            features_filtered = helpers.filter_df(
                DO.df, {"customer_name": customer, "type": ["Epic", "Feature"]}
            )
            parent_names[customer] = {
                "Epic": [],  # Epics have no parents
                "Feature": [
                    row["display_name"] for _, row in epics_filtered.iterrows()
                ],  # Features parent to Epics
                "User Story": [
                    row["display_name"] for _, row in features_filtered.iterrows()
                ],  # User Stories parent to Epics/Features
            }

        if tab_type == "Add":
            # Prepare customer-specific contacts and assignees
            contact_persons = {}
            assignees = {}
            default_assignee = {}

            for customer in customer_names:
                # Get customer-specific data from config
                customer_data = config_devops_contacts.get("customers", {}).get(
                    customer, {}
                )
                default_data = config_devops_contacts.get("default", {})

                # Use customer-specific contacts, or fall back to defaults
                contact_persons[customer] = customer_data.get(
                    "contacts", default_data.get("contacts", [])
                )
                assignees[customer] = customer_data.get(
                    "assignees", default_data.get("assignees", [])
                )
                # Get the default assignee for this customer
                default_assignee[customer] = customer_data.get("default_assignee", None)

            return {
                "customer_data": customer_names,
                "work_items": work_items,
                "parent_names": parent_names,
                "devops_tags": DEVOPS_TAGS,
                "contact_persons": contact_persons,
                "assignees": assignees,
                "default_assignee": default_assignee,
            }
        elif tab_type == "Update":
            # Prepare customer-specific assignees for Update tab
            assignees = {}
            for customer in customer_names:
                # Get customer-specific data from config
                customer_data = config_devops_contacts.get("customers", {}).get(
                    customer, {}
                )
                default_data = config_devops_contacts.get("default", {})

                # Use customer-specific assignees, or fall back to defaults
                assignees[customer] = customer_data.get(
                    "assignees", default_data.get("assignees", [])
                )

            return {
                "customer_data": customer_names,
                "work_items": work_items,
                "assignees": assignees,
            }

        return {}

    # --- Wrapper Functions (Simple Entities) ---

    def build_customer_tab_panel(tab_type, container_dict):
        """Build customer tab panel using generic builder."""
        helpers.build_generic_tab_panel(
            entity_name="customer",
            tab_type=tab_type,
            container_dict=container_dict,
            config_source=config_ui,
            data_prep_func=prep_customer_data,
            on_success_callback=lambda: AD.refresh(),
        )

    def build_project_tab_panel(tab_type, container_dict):
        """Build project tab panel using generic builder."""
        helpers.build_generic_tab_panel(
            entity_name="project",
            tab_type=tab_type,
            container_dict=container_dict,
            config_source=config_ui,
            data_prep_func=prep_project_data,
            on_success_callback=lambda: AD.refresh(),
        )

    def build_bonus_tab_panel(tab_type, container_dict):
        """Build bonus tab panel using generic builder."""
        helpers.build_generic_tab_panel(
            entity_name="bonus",
            tab_type=tab_type,
            container_dict=container_dict,
            config_source=config_ui,
            data_prep_func=prep_bonus_data,
            on_success_callback=lambda: AD.refresh(),
        )

    def add_work_item(widgets):
        """Create a work item (Epic, Feature, or User Story) based on the selected type."""
        wid = helpers.parse_widget_values(widgets)

        work_item_type = wid["work_item_type"]
        title = wid["work_item_title"]
        description = wid.get("description_editor", "")

        # Build additional fields
        additional_fields = {
            "System.State": wid["state"],
            "System.Tags": ", ".join([t for t in wid.get("tags", [])]),
            "Microsoft.VSTS.Common.Priority": int(wid["priority"]),
            "System.AssignedTo": wid.get("assigned_to", ""),
        }

        # Handle parent relationship (only for Features and User Stories)
        parent_id = None
        if wid.get("parent_name") and work_item_type in ["Feature", "User Story"]:
            parent_id = int(helpers.extract_devops_id(wid["parent_name"]))

        # Map work item type to DevOps helper function
        helper_function_map = {
            "Epic": "create_epic",
            "Feature": "create_feature",
            "User Story": "create_user_story",
        }

        helper_function = helper_function_map.get(work_item_type, "create_user_story")

        success, message = DO.devops_helper(
            helper_function,
            customer_name=wid["customer_name"],
            title=title,
            description=description,
            additional_fields=additional_fields,
            markdown=True,  # wid.get("use_markdown", True)
            parent=parent_id,
        )
        state = "INFO" if success else "ERROR"
        LOG.log_msg(state, message)
        return success, message

    async def update_work_item_description(widgets):
        """Save the updated description back to DevOps."""
        c_name = widgets["customer_name"].value
        work_item_display = widgets["work_item"].value
        work_item_id = helpers.extract_devops_id(work_item_display)
        description = widgets["description_editor"].value or ""

        # Determine if it's markdown based on the editor's language
        is_markdown = (
            getattr(widgets.get("description_editor"), "language", "markdown")
            == "markdown"
        )

        if DO and DO.manager:
            status, msg = DO.manager.set_description(
                c_name, work_item_id, description, markdown=is_markdown
            )
            if status:
                LOG.log_msg("INFO", f"Description updated for work item {work_item_id}")
                return (
                    True,
                    f"Description updated successfully for work item {work_item_id}",
                )
            else:
                LOG.log_msg("ERROR", f"Failed to update description: {msg}")
                return False, f"Failed to update: {msg}"
        return False, "DevOps manager not available"

    async def update_work_item(widgets):
        """Save the updated work item fields back to DevOps."""
        c_name = widgets["customer_name"].value
        work_item_display = widgets["work_item"].value
        work_item_id = helpers.extract_devops_id(work_item_display)

        # Collect all fields that have values
        fields_to_update = {}

        # Description (always present)
        description = widgets["description_editor"].value or ""
        if description:
            fields_to_update["System.Description"] = description

        # State
        state = widgets.get("state")
        if state and state.value:
            fields_to_update["System.State"] = state.value

        # Assigned To
        assigned_to = widgets.get("assigned_to")
        if assigned_to and assigned_to.value:
            fields_to_update["System.AssignedTo"] = assigned_to.value

        # Priority
        priority = widgets.get("priority")
        if priority and priority.value:
            fields_to_update["Microsoft.VSTS.Common.Priority"] = int(priority.value)

        # Determine if description is markdown based on the editor's language
        is_markdown = (
            getattr(widgets.get("description_editor"), "language", "markdown")
            == "markdown"
        )

        if DO and DO.manager:
            status, msg = DO.manager.update_work_item_fields(
                c_name, work_item_id, fields_to_update, markdown=is_markdown
            )
            if status:
                LOG.log_msg("INFO", f"Work item {work_item_id} updated successfully")
                return (
                    True,
                    f"Work item {work_item_id} updated successfully",
                )
            else:
                LOG.log_msg("ERROR", f"Failed to update work item: {msg}")
                return False, f"Failed to update: {msg}"
        return False, "DevOps manager not available"

    def build_work_item_tab_panel(tab_type, container_dict):
        """Build work item tab panel using generic builder with DevOps-specific handlers."""

        # Custom handlers for DevOps operations
        custom_handlers = {
            "add_work_item": add_work_item,
            "update_work_item_description": update_work_item_description,
            "update_work_item": update_work_item,
        }

        # Render functions for HTML preview
        render_functions = {"render_and_sanitize": helpers.render_and_sanitize_markdown}

        # Set container size based on tab type - Update tab needs more space for editor/preview
        container_size = "xxl" if tab_type == "Update" else "lg"

        # Use generic builder and get back the widgets
        widgets = helpers.build_generic_tab_panel(
            entity_name="devops_work_item",
            tab_type=tab_type,
            container_dict=container_dict,
            config_source=config_ui,
            data_prep_func=prep_devops_data,
            custom_handlers=custom_handlers,
            render_functions=render_functions,
            container_size=container_size,
        )

        # Add special event handlers for Update tab (description editor/preview and loading)
        if tab_type == "Update" and widgets:
            editor_widget = widgets.get("description_editor")
            preview_html = widgets.get("description_preview")
            work_item_widget = widgets.get("work_item")
            customer_widget = widgets.get("customer_name")
            state_widget = widgets.get("state")
            assigned_to_widget = widgets.get("assigned_to")
            priority_widget = widgets.get("priority")

            # Set up editor preview update
            if editor_widget and preview_html:

                def update_preview():
                    preview_html.set_content(
                        helpers.render_and_sanitize_markdown(editor_widget.value)
                    )

                editor_widget.on_value_change(update_preview)

            # Set up work item details loader
            if work_item_widget and customer_widget and editor_widget and preview_html:

                async def load_work_item_details(e):
                    """Load all work item details when work item is selected."""
                    c_name = customer_widget.value
                    work_item_display = work_item_widget.value

                    if not c_name or not work_item_display:
                        return

                    work_item_id = helpers.extract_devops_id(work_item_display)

                    if DO.manager:
                        # Get full work item details
                        status, details = DO.manager.get_work_item_details(
                            customer_name=c_name, work_item_id=work_item_id
                        )

                        if status:
                            # Update description
                            description_raw = details.get("description", "")

                            # Check if the content appears to be HTML (contains HTML tags)
                            is_html_content = bool(
                                description_raw
                                and ("<" in description_raw and ">" in description_raw)
                            )

                            if is_html_content:
                                # Convert HTML to markdown for better readability in editor
                                description_clean = helpers.convert_html_to_markdown(
                                    description_raw
                                )
                            else:
                                # Just unescape HTML entities for plain text/markdown content
                                description_clean = html.unescape(description_raw)

                            editor_widget.value = description_clean
                            editor_widget.update()
                            preview_html.set_content(
                                helpers.render_and_sanitize_markdown(description_clean)
                            )

                            # Update other fields
                            if state_widget and details.get("state"):
                                try:
                                    state_value = details["state"]
                                    # Try both methods for setting the value
                                    state_widget.set_value(state_value)
                                    state_widget.value = state_value
                                except Exception as e:
                                    LOG.log_msg(
                                        "WARNING", f"Failed to set state widget: {e}"
                                    )

                            if assigned_to_widget and details.get("assigned_to"):
                                try:
                                    # Get the raw assigned_to field from DevOps to extract email
                                    assigned_to_raw = details.get("assigned_to_raw")
                                    assigned_to_display = details["assigned_to"]

                                    # Try to use the email address (uniqueName) if available
                                    if assigned_to_raw and isinstance(
                                        assigned_to_raw, dict
                                    ):
                                        assigned_to_value = assigned_to_raw.get(
                                            "uniqueName", assigned_to_display
                                        )
                                    else:
                                        assigned_to_value = assigned_to_display

                                    # Check if the value is in the dropdown options
                                    widget_options = getattr(
                                        assigned_to_widget, "options", []
                                    )
                                    if assigned_to_value in widget_options:
                                        assigned_to_widget.set_value(assigned_to_value)
                                        assigned_to_widget.value = assigned_to_value
                                    else:
                                        # For combobox widgets (with_input: true), we can set custom values
                                        assigned_to_widget.set_value(
                                            assigned_to_display
                                        )
                                        assigned_to_widget.value = assigned_to_display
                                except Exception as e:
                                    LOG.log_msg(
                                        "WARNING",
                                        f"Failed to set assigned_to widget: {e}",
                                    )

                            if priority_widget and details.get("priority") is not None:
                                try:
                                    # Convert to integer to match widget options
                                    priority_value = int(details["priority"])
                                    # Try both methods for setting the value
                                    priority_widget.set_value(priority_value)
                                    priority_widget.value = priority_value
                                except Exception as e:
                                    LOG.log_msg(
                                        "WARNING", f"Failed to set priority widget: {e}"
                                    )
                        else:
                            ui.notify(
                                f"Failed to load work item details: {details}",
                                color="negative",
                            )
                            LOG.log_msg(
                                "ERROR", f"Failed to load work item details: {details}"
                            )

                work_item_widget.on("update:model-value", load_work_item_details)

        # Add special event handlers for Add tab (auto-populate source and contact)
        if tab_type == "Add" and widgets:
            editor_widget = widgets.get("description_editor")
            preview_widget = widgets.get("description_preview")
            source_widget = widgets.get("source")
            contact_widget = widgets.get("contact_person")

            # Initialize the preview with the initial editor content
            if editor_widget and preview_widget:
                initial_content = editor_widget.value or ""
                preview_widget.set_content(
                    helpers.render_and_sanitize_markdown(initial_content)
                )

            if editor_widget and (source_widget or contact_widget):
                import re

                def update_editor_field(field_name, new_value):
                    """Update a specific field in the markdown editor."""
                    current_text = editor_widget.value or ""

                    # Debug: log the current text to see what we're working with
                    LOG.log_msg(
                        "DEBUG",
                        f"Updating field '{field_name}' with value '{new_value}'",
                    )
                    LOG.log_msg(
                        "DEBUG", f"Current editor content:\n{repr(current_text[:200])}"
                    )

                    # Match the field and update its value (only the content after the field name)
                    # Pattern: **FieldName:** followed by optional spaces/content until newline
                    # We need to match the entire line including trailing whitespace
                    pattern = rf"^(\*\*{re.escape(field_name)}:\*\*)(.*)$"

                    # Check if the pattern exists in the text (using MULTILINE flag)
                    match = re.search(pattern, current_text, re.MULTILINE)
                    if match:
                        LOG.log_msg(
                            "DEBUG", f"Pattern matched! Groups: {match.groups()}"
                        )
                        # Replace with the field name followed by a space and the new value
                        replacement = rf"\1 {new_value}"
                        updated_text = re.sub(
                            pattern,
                            replacement,
                            current_text,
                            count=1,
                            flags=re.MULTILINE,
                        )
                    else:
                        # If pattern not found, just return without updating
                        LOG.log_msg(
                            "WARNING", f"Pattern for '{field_name}' not found in editor"
                        )
                        LOG.log_msg("DEBUG", f"Searched for pattern: {pattern}")
                        return

                    editor_widget.value = updated_text
                    editor_widget.update()

                    # Also update the preview
                    if preview_widget:
                        preview_widget.set_content(
                            helpers.render_and_sanitize_markdown(updated_text)
                        )

                if source_widget:

                    def on_source_change(e):
                        # Get the new value from the widget directly
                        new_value = source_widget.value or ""
                        update_editor_field("Source", new_value)

                    source_widget.on("update:model-value", on_source_change)

                if contact_widget:

                    def on_contact_change(e):
                        # Get the new value from the widget directly
                        new_value = contact_widget.value or ""
                        update_editor_field("Contact", new_value)

                    contact_widget.on("update:model-value", on_contact_change)

    def build_database_compare():
        def handle_upload(e: events.UploadEventArguments):
            ui.notify(f"File uploaded: {e.name}", color="positive")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                tmp.write(e.content.read())
                uploaded_path = tmp.name

            sync_sql = Database.generate_sync_sql(MAIN_DB, uploaded_path)
            db_deltas.set_content(sync_sql)
            db_deltas.update()
            os.remove(uploaded_path)  # Clean up temp file

        with ui.card().classes(UI_STYLES.get_card_classes("xs", "card")):
            ui.label("Upload a .db file to compare with the main database.").classes(
                UI_STYLES.get_layout_classes("title").replace("mb-4", "mb-0 dense")
            )
            ui.upload(on_upload=handle_upload).props("accept=.db").classes(
                "q-pa-xs q-ma-xs"
            )
            ui.separator().classes("my-4")
            ui.label("SQL to synchronize uploaded DB:").classes(
                UI_STYLES.get_layout_classes("subtitle")
            )
            db_deltas = (
                ui.code("--temp location of sql-changes...", language="sql")
                .props("readonly")
                .classes(UI_STYLES.get_widget_style("code_display", "large")["classes"])
            )

    def build_database_update():
        uploaded_db_path = None
        original_db_filename = None

        def handle_upload(e: events.UploadEventArguments):
            nonlocal uploaded_db_path, original_db_filename
            ui.notify(f"File uploaded: {e.name}", color="positive")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                tmp.write(e.content.read())
                uploaded_db_path = tmp.name
                original_db_filename = e.name if hasattr(e, "name") else "database.db"
            result_box.set_content(f"-- Uploaded DB: {uploaded_db_path}")
            result_box.update()

        def run_sql():
            if not uploaded_db_path:
                ui.notify("No uploaded DB!", color="negative")
                return
            import sqlite3

            try:
                conn = sqlite3.connect(uploaded_db_path)

                cursor = conn.cursor()
                query = (
                    sql_input.value if hasattr(sql_input, "value") else sql_input.text
                )
                cursor.executescript(query)
                conn.commit()

                # Try to fetch results if it's a SELECT
                if query.strip().lower().startswith("select"):
                    cursor.execute(query)
                    rows = cursor.fetchall()
                    columns = [desc[0] for desc in cursor.description]
                    result = (
                        "\t".join(columns)
                        + "\n"
                        + "\n".join(
                            ["\t".join(str(cell) for cell in row) for row in rows]
                        )
                    )
                else:
                    result = "Query executed successfully."
                    ui.notify("Query executed successfully.", color="positive")
                conn.close()
                result_box.set_content(result)
                result_box.update()
            except Exception as e:
                result_box.set_content(f"Error: {e}")
                result_box.update()

        with ui.card().classes(UI_STYLES.get_card_classes("xs", "card")):
            ui.label("Upload a .db file to run SQL queries on.").classes(
                UI_STYLES.get_layout_classes("title").replace("mb-4", "mb-0 dense")
            )
            ui.upload(on_upload=handle_upload).props("accept=.db").classes(
                "q-pa-xs q-ma-xs mb-2"
            )
            with ui.row().classes("w-full mb-2"):
                ui.button("Run SQL", on_click=run_sql).classes("mr-2")

                def download_db():
                    if not uploaded_db_path:
                        ui.notify("No uploaded DB!", color="negative")
                        return
                    # Serve the file for download with the original filename
                    filename = (
                        original_db_filename
                        if original_db_filename
                        else os.path.basename(uploaded_db_path)
                    )
                    ui.download(uploaded_db_path, filename)

                ui.button("Download DB", on_click=download_db)

        sql_input = ui.codemirror(
            "-- Enter SQL query here --",
            language="SQLite",
            theme="dracula",
        ).classes(UI_STYLES.get_widget_style("code_display", "small")["classes"])

        result_box = ui.code("-- Results will appear here --", language="sql").classes(
            UI_STYLES.get_widget_style("code_display", "medium")["classes"]
        )

    tab_list = {}
    vertical_tab_entries = [i for i in config_ui]

    with ui.splitter(value=20).classes("w-full h-full") as splitter:
        with splitter.before:
            with ui.tabs().props("vertical").classes("w-full") as main_tabs:
                for tab in vertical_tab_entries:
                    meta_data = config_ui[tab].get("meta", {})
                    tab_list[tab] = {
                        "tab": ui.tab(
                            meta_data.get("friendly_name", tab.capitalize()),
                            icon=meta_data.get("icon", "folder"),
                        ),
                        "name": tab,
                        "tab_list": [],
                        "tab_container": {},
                        "build_function": meta_data.get("build_function", None),
                        "friendly_name": meta_data.get(
                            "friendly_name", tab.capitalize()
                        ),
                    }
                tab_database = ui.tab("Database", icon="storage")
        with splitter.after:
            with (
                ui.tab_panels(
                    main_tabs, value=tab_list[vertical_tab_entries[0]]["friendly_name"]
                )
                .props("vertical")
                .classes("w-full h-full")
            ):

                async def on_tab_change(e, function, container):
                    tab_type = e.args
                    await AD.refresh()
                    function(tab_type, container)

                # Define function map after all functions are available
                function_map = {
                    "build_customer_tab_panel": build_customer_tab_panel,
                    "build_project_tab_panel": build_project_tab_panel,
                    "build_bonus_tab_panel": build_bonus_tab_panel,
                    "build_work_item_tab_panel": build_work_item_tab_panel,
                }

                for tab_dict in tab_list.values():
                    tab_names = [
                        i.capitalize()
                        for i in helpers.get_ui_elements(config_ui[tab_dict["name"]])
                    ]

                    with ui.tab_panel(tab_dict["tab"]):
                        with ui.tabs().classes("mb-2") as temp_tab:
                            for name in tab_names:
                                tab_dict["tab_list"].append(ui.tab(name))
                        # Only create tab_panels if there are tabs to display
                        if tab_dict["tab_list"]:
                            with ui.tab_panels(temp_tab, value=tab_dict["tab_list"][0]):
                                for i, name in enumerate(tab_names):
                                    with ui.tab_panel(tab_dict["tab_list"][i]):
                                        function_map[tab_dict["build_function"]](
                                            name, tab_dict["tab_container"]
                                        )
                            temp_tab.on(
                                "update:model-value",
                                lambda e,
                                function=function_map[tab_dict["build_function"]],
                                container=tab_dict["tab_container"]: on_tab_change(
                                    e,
                                    function,
                                    container,
                                ),
                            )

                # Database
                with ui.tab_panel(tab_database):
                    with ui.tabs().classes("mb-2") as database_tabs:
                        tab_add = ui.tab("Schema Compare")
                        tab_update = ui.tab("Update DB")

                    with ui.tab_panels(database_tabs, value=tab_add):
                        with ui.tab_panel(tab_add):
                            build_database_compare()
                        with ui.tab_panel(tab_update):
                            build_database_update()
