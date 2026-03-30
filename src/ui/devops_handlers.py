"""
DevOps Work Item Handlers

Custom handlers and event bindings for DevOps work item forms.
These handle special logic for creating/updating work items and managing the description editor.
"""

import html
import re

from nicegui import ui

from .. import helpers


class DevOpsWorkItemHandlers:
    """Handlers for DevOps work item operations."""

    def __init__(self, DO, LOG):
        """
        Initialize DevOps handlers.

        Args:
            DO: DevOpsEngine instance
            LOG: Logger instance
        """
        self.DO = DO
        self.LOG = LOG

    def add_work_item(self, widgets):
        """
        Create a work item (Epic, Feature, or User Story) based on the selected type.

        Args:
            widgets: Dictionary of form widgets

        Returns:
            Tuple of (success: bool, message: str)
        """
        wid = helpers.parse_widget_values(widgets)

        work_item_type = wid["work_item_type"]
        title = wid["work_item_title"]
        description = wid.get("description_editor", "")

        # Build additional fields
        additional_fields = {
            "System.State": wid["state"],
            "System.Tags": wid.get("tags", ""),
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

        success, message = self.DO.devops_helper(
            helper_function,
            customer_name=wid["customer_name"],
            title=title,
            description=description,
            additional_fields=additional_fields,
            markdown=True,
            parent=parent_id,
        )
        if success:
            self.LOG.info(message)
        else:
            self.LOG.error(message)
        return success, message

    async def update_work_item_description(self, widgets):
        """
        Save the updated description back to DevOps.

        Args:
            widgets: Dictionary of form widgets

        Returns:
            Tuple of (success: bool, message: str)
        """
        c_name = widgets["customer_name"].value
        work_item_display = widgets["work_item"].value
        work_item_id = helpers.extract_devops_id(work_item_display)
        description = widgets["description_editor"].value or ""

        # Determine if it's markdown based on the editor's language
        is_markdown = (
            getattr(widgets.get("description_editor"), "language", "markdown")
            == "markdown"
        )

        if self.DO and self.DO.manager:
            status, msg = self.DO.manager.set_description(
                c_name, work_item_id, description, markdown=is_markdown
            )
            if status:
                self.LOG.info(f"Description updated for work item {work_item_id}")
                return (
                    True,
                    f"Description updated successfully for work item {work_item_id}",
                )
            else:
                self.LOG.error(f"Failed to update description: {msg}")
                return False, f"Failed to update: {msg}"
        return False, "DevOps manager not available"

    async def update_work_item(self, widgets):
        """
        Save the updated work item fields back to DevOps.

        Args:
            widgets: Dictionary of form widgets

        Returns:
            Tuple of (success: bool, message: str)
        """
        c_name = widgets["customer_name"].value
        work_item_display = widgets["work_item"].value
        work_item_id = helpers.extract_devops_id(work_item_display)

        fields_to_update = {}

        description = widgets["description_editor"].value or ""
        if description:
            fields_to_update["System.Description"] = description

        state = widgets.get("state")
        if state and state.value:
            fields_to_update["System.State"] = state.value

        assigned_to = widgets.get("assigned_to")
        if assigned_to and assigned_to.value:
            fields_to_update["System.AssignedTo"] = assigned_to.value

        priority = widgets.get("priority")
        if priority and priority.value:
            fields_to_update["Microsoft.VSTS.Common.Priority"] = int(priority.value)

        is_markdown = (
            getattr(widgets.get("description_editor"), "language", "markdown")
            == "markdown"
        )

        if not self.DO or not self.DO.manager:
            return (False, "DevOps manager not available")

        # Update regular fields first
        if fields_to_update:
            status, msg = self.DO.manager.update_work_item_fields(
                c_name, work_item_id, fields_to_update, markdown=is_markdown
            )
            if not status:
                self.LOG.error(f"Failed to update work item fields: {msg}")
                return (False, f"Failed to update: {msg}")

        # Move board column separately via REST if specified
        board_column = widgets.get("board_column")
        if board_column and board_column.value:
            col_success, col_msg = self.DO.manager.set_board_column(
                customer_name=c_name,
                work_item_id=work_item_id,
                column_name=board_column.value,
            )
            if not col_success:
                self.LOG.warning(f"Board column move failed: {col_msg}")
                return (True, f"Fields updated but column move failed: {col_msg}")

        self.LOG.info(f"Work item {work_item_id} updated successfully")
        return (True, f"Work item {work_item_id} updated successfully")

    def setup_update_tab_handlers(self, widgets):
        editor_widget = widgets.get("description_editor")
        work_item_widget = widgets.get("work_item")
        customer_widget = widgets.get("customer_name")
        state_widget = widgets.get("state")
        assigned_to_widget = widgets.get("assigned_to")
        priority_widget = widgets.get("priority")
        board_column_widget = widgets.get("board_column")
        current_column_widget = widgets.get("current_column")

        async def load_work_item_details(e):
            c_name = customer_widget.value
            work_item_display = work_item_widget.value
            if not c_name or not work_item_display:
                return
            work_item_id = helpers.extract_devops_id(work_item_display)
            if not self.DO.manager:
                return

            status, details = self.DO.manager.get_work_item_details(
                customer_name=c_name, work_item_id=work_item_id
            )
            if not status:
                ui.notify(
                    f"Failed to load work item details: {details}", color="negative"
                )
                self.LOG.error(f"Failed to load work item details: {details}")
                return

            # Description
            description_raw = details.get("description", "")
            is_html_content = bool(
                description_raw and ("<" in description_raw and ">" in description_raw)
            )
            description_clean = (
                helpers.convert_html_to_markdown(description_raw)
                if is_html_content
                else html.unescape(description_raw)
            )
            editor_widget.value = description_clean

            # Standard fields
            self._set_widget_value_safe(state_widget, details.get("state"), "string")
            self._set_widget_value_safe(
                assigned_to_widget,
                details.get("assigned_to_raw") or details.get("assigned_to"),
                "assignee",
            )
            self._set_widget_value_safe(priority_widget, details.get("priority"), "int")

            # Current column — readonly display
            current_col = details.get("board_column", "")
            if current_column_widget:
                self._set_widget_value_safe(
                    current_column_widget, current_col, "string"
                )
                current_column_widget.widget.props("readonly outlined")

            # Load available board columns directly from the work item
            col_status, columns = self.DO.manager.get_board_columns_for_item(
                customer_name=c_name, work_item_id=work_item_id
            )
            self.LOG.info(
                f"Board columns for item {work_item_id}: {col_status} {columns}"
            )
            if col_status and board_column_widget:
                board_column_widget.widget.options = columns
                if current_col:
                    self._set_widget_value_safe(
                        board_column_widget, current_col, "string"
                    )
                board_column_widget.widget.update()
            else:
                self.LOG.warning(f"Could not load board columns: {columns}")

        if work_item_widget:
            work_item_widget.on("update:model-value", load_work_item_details)

    def setup_add_tab_handlers(self, widgets):
        """
        Set up special event handlers for the Add tab.

        Handles:
        - Auto-populate Source and Contact fields in description editor
        - Preview synchronization

        Args:
            widgets: Dictionary of form widgets
        """
        editor_widget = widgets.get("description_editor")
        preview_widget = widgets.get("description_preview")
        source_widget = widgets.get("source")
        contact_widget = widgets.get("contact_person")

        # Initialize preview
        if editor_widget and preview_widget:
            initial_content = editor_widget.value or ""
            preview_widget.set_content(
                helpers.render_and_sanitize_markdown(initial_content)
            )
            # Note: Preview updates automatically via parent-child binding with polling

        # Set up field updaters
        if editor_widget and (source_widget or contact_widget):

            def update_editor_field(field_name, new_value):
                """Update a specific field in the markdown editor."""
                current_text = editor_widget.value or ""
                pattern = rf"^(\*\*{re.escape(field_name)}:\*\*)(.*)$"

                match = re.search(pattern, current_text, re.MULTILINE)
                if match:
                    replacement = rf"\1 {new_value}"
                    updated_text = re.sub(
                        pattern,
                        replacement,
                        current_text,
                        count=1,
                        flags=re.MULTILINE,
                    )
                    editor_widget.value = updated_text
                    editor_widget.update()
                    # Note: preview will be updated automatically by on_value_change handler

            if source_widget:

                def on_source_change(e):
                    update_editor_field("Source", source_widget.value or "")

                source_widget.on("update:model-value", on_source_change)

            if contact_widget:

                def on_contact_change(e):
                    update_editor_field("Contact", contact_widget.value or "")

                contact_widget.on("update:model-value", on_contact_change)

    def _set_widget_value_safe(self, widget, value, value_type="string"):
        """
        Safely set widget value with type-specific handling.

        Args:
            widget: NiceGUI widget to update
            value: Value to set
            value_type: "string", "assignee", or "int"
        """
        if not widget or value is None:
            return

        try:
            if value_type == "assignee":
                # Special handling for assignee widgets
                # Try to extract email if value is a dict
                if isinstance(value, dict):
                    assignee_value = value.get(
                        "uniqueName", value.get("displayName", "")
                    )
                else:
                    assignee_value = value

                # Check if value is in dropdown options
                widget_options = getattr(widget, "options", [])
                if assignee_value in widget_options:
                    widget.set_value(assignee_value)
                    widget.value = assignee_value
                else:
                    # For combobox widgets, we can set custom values
                    widget.set_value(assignee_value)
                    widget.value = assignee_value

            elif value_type == "int":
                # Convert to int if needed
                int_value = int(value) if value is not None else None
                if int_value is not None:
                    widget.set_value(int_value)
                    widget.value = int_value

            else:  # string or default
                widget.set_value(value)
                widget.value = value

        except Exception as e:
            self.LOG.warning(f"Failed to set widget value (type={value_type}): {e}")
