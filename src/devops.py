from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v7_1.work_item_tracking.models import CommentCreate
from azure.devops.exceptions import AzureDevOpsServiceError
import pandas as pd
import re


class DevOpsManager:
    def __init__(self, df, log):
        self.clients = {}
        self.log = log
        for _, row in df.iterrows():
            if row["org_url"].lower() in ["", "none", "null"] or row[
                "pat_token"
            ].lower() in ["", "none", "null"]:
                continue
            org_url = f"https://dev.azure.com/{row['org_url']}"
            client = DevOpsClient(row["pat_token"], org_url, self.log)
            try:
                client.connect()
                self.clients[row["customer_name"]] = client
                self.log.log_msg(
                    "INFO", f"Connected to DevOps for customer {row['customer_name']}"
                )
            except Exception as e:
                self.log.log_msg(
                    "Error",
                    f"DevOps connection failed for {row['customer_name']}:\n{e}",
                )

    def save_comment(self, customer_name, comment, git_id):
        client = self.clients.get(customer_name)
        if not client:
            self.log.log_msg("WARNING", f"No DevOps connection for {customer_name}")
            return f"No DevOps connection for {customer_name}"
        return client.add_comment_to_work_item(git_id, comment)

    def get_workitem_level(self, customer_name, level=None, work_item_id=None):
        client = self.clients.get(customer_name)
        if not client:
            self.log.log_msg("WARNING", f"No DevOps connection for {customer_name}")
            return f"No DevOps connection for {customer_name}"
        return client.get_workitem_level(level, work_item_id)

    def get_description(self, customer_name, work_item_id):
        """Return the work item's description (System.Description) as plain text.

        Returns (True, description) on success or (False, message) on failure.
        """
        client = self.clients.get(customer_name)
        if not client:
            self.log.log_msg("WARNING", f"No DevOps connection for {customer_name}")
            return (False, f"No DevOps connection for {customer_name}")
        return client.get_work_item_description(work_item_id)

    def set_description(self, customer_name, work_item_id, description, markdown=False):
        """Set (update) a work item's description. Returns (True, msg) or (False, msg)."""
        client = self.clients.get(customer_name)
        if not client:
            self.log.log_msg("WARNING", f"No DevOps connection for {customer_name}")
            return (False, f"No DevOps connection for {customer_name}")
        return client.update_work_item_description(work_item_id, description, markdown)

    def update_work_item_fields(self, customer_name, work_item_id, fields, markdown=False):
        """Update multiple fields of a work item. Returns (True, msg) or (False, msg)."""
        client = self.clients.get(customer_name)
        if not client:
            self.log.log_msg("WARNING", f"No DevOps connection for {customer_name}")
            return (False, f"No DevOps connection for {customer_name}")
        return client.update_work_item_fields(work_item_id, fields, markdown)

    def get_work_item_details(self, customer_name, work_item_id):
        """Get work item details. Returns (True, details_dict) or (False, error_msg)."""
        client = self.clients.get(customer_name)
        if not client:
            self.log.log_msg("WARNING", f"No DevOps connection for {customer_name}")
            return (False, f"No DevOps connection for {customer_name}")
        return client.get_work_item_details(work_item_id)

    def create_user_story(
        self,
        customer_name,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        client = self.clients.get(customer_name)
        if not client:
            self.log.log_msg("WARNING", f"No DevOps connection for {customer_name}")
            return (False, f"No DevOps connection for {customer_name}")
        return client.create_user_story(
            title, description, additional_fields, markdown, parent
        )

    def create_epic(
        self,
        customer_name,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
    ):
        client = self.clients.get(customer_name)
        if not client:
            self.log.log_msg("WARNING", f"No DevOps connection for {customer_name}")
            return (False, f"No DevOps connection for {customer_name}")
        return client.create_epic(
            title, description, additional_fields, markdown
        )

    def create_feature(
        self,
        customer_name,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        client = self.clients.get(customer_name)
        if not client:
            self.log.log_msg("WARNING", f"No DevOps connection for {customer_name}")
            return (False, f"No DevOps connection for {customer_name}")
        return client.create_feature(
            title, description, additional_fields, markdown, parent
        )

    def get_epics_feature_df(self, max_ids: dict = None):
        """Get work items in long format with parent_id column.

        Args:
            max_ids: Dict of {customer_name: max_id} for incremental refresh
        """
        rows = []
        for customer_name, client in self.clients.items():
            # Get customer-specific min_id for filtering
            min_id = max_ids.get(customer_name) if max_ids else None

            status, items = client.get_workitem_level(
                level=None, return_full=True, min_id=min_id
            )
            if not status or not items:
                continue

            # Build lookup dicts for hierarchy
            epics = {
                item.id: item
                for item in items
                if getattr(item, "fields", {}).get("System.WorkItemType") == "Epic"
            }
            features = {
                item.id: item
                for item in items
                if getattr(item, "fields", {}).get("System.WorkItemType") == "Feature"
            }
            user_stories = {
                item.id: item
                for item in items
                if getattr(item, "fields", {}).get("System.WorkItemType")
                == "User Story"
            }

            # Add all epics
            for epic in epics.values():
                rows.append(
                    {
                        "customer_name": customer_name,
                        "type": "Epic",
                        "id": epic.id,
                        "title": epic.fields.get("System.Title"),
                        "state": epic.fields.get("System.State"),
                        "parent_id": None,
                    }
                )

            # Add all features
            for feature in features.values():
                parent_id = feature.fields.get("System.Parent")
                # Store parent_id even if the parent wasn't in this fetch (for incremental updates)
                rows.append(
                    {
                        "customer_name": customer_name,
                        "type": "Feature",
                        "id": feature.id,
                        "title": feature.fields.get("System.Title"),
                        "state": feature.fields.get("System.State"),
                        "parent_id": parent_id,  # Store the parent_id regardless
                    }
                )

            # Add all user stories
            for us in user_stories.values():
                parent_id = us.fields.get("System.Parent")
                # Store parent_id even if the parent wasn't in this fetch (for incremental updates)
                rows.append(
                    {
                        "customer_name": customer_name,
                        "type": "User Story",
                        "id": us.id,
                        "title": us.fields.get("System.Title"),
                        "state": us.fields.get("System.State"),
                        "parent_id": parent_id,  # Store the parent_id regardless
                    }
                )

        df = pd.DataFrame(rows)
        return (True, df)


class DevOpsClient:
    def __init__(self, personal_access_token, organization_url, log):
        self.personal_access_token = personal_access_token
        self.organization_url = organization_url
        self.log = log

    def connect(self):
        # Create a connection to the Azure DevOps organization
        try:
            credentials = BasicAuthentication("", self.personal_access_token)
            self.connection = Connection(
                base_url=self.organization_url, creds=credentials
            )
            self.wit_client = self.get_work_item_tracking_client()

            # Attempt a simple call to ensure connection is valid
            core_client = self.connection.clients.get_core_client()

            project_list = core_client.get_projects(top=1)  # This is a list now
            self.project_name = project_list[0].name  # Get the first project's name

        except Exception as e:
            msg = str(e).lower()
            if "expired" in msg or "revoked" in msg or "unauthorized" in msg:
                self.log.log_msg(
                    "ERROR",
                    "Your Personal Access Token has expired or been revoked. Please renew it.",
                )
                raise Exception(
                    "Your Personal Access Token has expired or been revoked. Please renew it."
                )
            else:
                self.log.log_msg("ERROR", f"Failed to connect to Azure DevOps: {e}")
                raise Exception(f"Failed to connect to Azure DevOps: {e}")

    def get_work_item_tracking_client(self):
        if not self.connection:
            self.log.log_msg(
                "ERROR", "Connection not established. Call connect() first."
            )
            raise Exception("Connection not established. Call connect() first.")
        return self.connection.clients.get_work_item_tracking_client()

    def add_comment_to_work_item(self, work_item_id, comment_text):
        comment_text = comment_text.replace("\n", "<br>")  # Fix for new lines
        try:
            comment_obj = CommentCreate(text=comment_text)
            self.wit_client.add_comment(
                request=comment_obj,
                project=self.project_name,
                work_item_id=work_item_id,
            )
        except AzureDevOpsServiceError as e:
            if (
                hasattr(e, "inner_exception")
                and getattr(e.inner_exception, "status_code", None) == 404
            ):
                self.log.log_msg(
                    "WARNING", f"Work item with ID {work_item_id} does not exist."
                )
                return (False, f"Work item with ID {work_item_id} does not exist.")
            else:
                self.log.log_msg("ERROR", f"Azure DevOps error occurred: {e}")
                return (False, f"Azure DevOps error occurred: {e}")
        return (True, "Comment added successfully.")

    def get_workitem_level(
        self,
        level: str = None,
        work_item_id: int = None,
        return_full=False,
        min_id: int = None,
    ):
        def batched(iterable, n):
            for i in range(0, len(iterable), n):
                yield iterable[i : i + n]

        query = f"""
            SELECT [System.Id], [System.Title], [System.State], [System.WorkItemType]
            FROM WorkItems
            WHERE [System.TeamProject] = '{self.project_name}'
        """
        if level:
            query += f" AND [System.WorkItemType] = '{level}'"
        if work_item_id:
            query += f" AND [System.Id] = {work_item_id}"
        if min_id is not None:
            query += f" AND [System.Id] > {min_id}"
        wiql_query = {"query": query}
        try:
            result = self.wit_client.query_by_wiql(wiql=wiql_query)
            ids = [item.id for item in result.work_items]
            if not ids:
                return (False, "No work items found.")
            all_items = []
            for batch in batched(ids, 200):
                items = self.wit_client.get_work_items(batch, expand="All")
                all_items.extend(items)
            if work_item_id:
                # Return the title of the single work item
                title = all_items[0].fields.get("System.Title", None)
                if title:
                    return (True, title)
                else:
                    return (False, "Title not found for work item.")
            else:
                if return_full:
                    return (True, all_items)
                epic_list = [
                    f"{item.id} - {item.fields['System.Title']}" for item in all_items
                ]
                return (True, epic_list)
        except Exception as e:
            self.log.log_msg("ERROR", f"Error fetching work items: {e}")
            return (False, f"Error fetching work items: {e}")

    def create_user_story(
        self,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        """Create a new User Story work item in Azure DevOps."""
        try:
            patch_document = [
                {"op": "add", "path": "/fields/System.Title", "value": title}
            ]
            if description:
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/fields/System.Description",
                        "value": description,
                    }
                )
            if additional_fields:
                for field, value in additional_fields.items():
                    if value is not None:
                        patch_document.append(
                            {"op": "add", "path": f"/fields/{field}", "value": value}
                        )
            if markdown:
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/multilineFieldsFormat/System.Description",
                        "value": "Markdown",
                    }
                )
            if parent:
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/relations/-",
                        "value": {
                            "rel": "System.LinkTypes.Hierarchy-Reverse",
                            "url": f"{self.organization_url}/{self.project_name}/_apis/wit/workItems/{parent}",
                        },
                    }
                )

            work_item = self.wit_client.create_work_item(
                patch_document, project=self.project_name, type="User Story"
            )
            self.log.log_msg("INFO", f"Created User Story with ID {work_item.id}")
            return (True, f"Created User Story with ID {work_item.id}")
        except AzureDevOpsServiceError as e:
            self.log.log_msg("ERROR", f"Azure DevOps error occurred: {e}")
            return (False, f"Azure DevOps error occurred: {e}")
        except Exception as e:
            self.log.log_msg("ERROR", f"Error creating user story: {e}")
            return (False, f"Error creating user story: {e}")

    def create_epic(
        self,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
    ):
        """Create a new Epic work item in Azure DevOps."""
        try:
            patch_document = [
                {"op": "add", "path": "/fields/System.Title", "value": title}
            ]
            if description:
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/fields/System.Description",
                        "value": description,
                    }
                )
            if additional_fields:
                for field, value in additional_fields.items():
                    if value is not None:
                        patch_document.append(
                            {"op": "add", "path": f"/fields/{field}", "value": value}
                        )
            if markdown:
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/multilineFieldsFormat/System.Description",
                        "value": "Markdown",
                    }
                )

            work_item = self.wit_client.create_work_item(
                patch_document, project=self.project_name, type="Epic"
            )
            self.log.log_msg("INFO", f"Created Epic with ID {work_item.id}")
            return (True, f"Created Epic with ID {work_item.id}")
        except AzureDevOpsServiceError as e:
            self.log.log_msg("ERROR", f"Azure DevOps error occurred: {e}")
            return (False, f"Azure DevOps error occurred: {e}")
        except Exception as e:
            self.log.log_msg("ERROR", f"Error creating epic: {e}")
            return (False, f"Error creating epic: {e}")

    def create_feature(
        self,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        """Create a new Feature work item in Azure DevOps."""
        try:
            patch_document = [
                {"op": "add", "path": "/fields/System.Title", "value": title}
            ]
            if description:
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/fields/System.Description",
                        "value": description,
                    }
                )
            if additional_fields:
                for field, value in additional_fields.items():
                    if value is not None:
                        patch_document.append(
                            {"op": "add", "path": f"/fields/{field}", "value": value}
                        )
            if markdown:
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/multilineFieldsFormat/System.Description",
                        "value": "Markdown",
                    }
                )
            if parent:
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/relations/-",
                        "value": {
                            "rel": "System.LinkTypes.Hierarchy-Reverse",
                            "url": f"{self.organization_url}/{self.project_name}/_apis/wit/workItems/{parent}",
                        },
                    }
                )

            work_item = self.wit_client.create_work_item(
                patch_document, project=self.project_name, type="Feature"
            )
            self.log.log_msg("INFO", f"Created Feature with ID {work_item.id}")
            return (True, f"Created Feature with ID {work_item.id}")
        except AzureDevOpsServiceError as e:
            self.log.log_msg("ERROR", f"Azure DevOps error occurred: {e}")
            return (False, f"Azure DevOps error occurred: {e}")
        except Exception as e:
            self.log.log_msg("ERROR", f"Error creating feature: {e}")
            return (False, f"Error creating feature: {e}")

    def get_work_item_description(self, work_item_id: int):
        """Return the System.Description field for a single work item as plain text.

        Returns (True, description) or (False, message).
        """
        try:
            item = self.wit_client.get_work_item(int(work_item_id), expand="All")
            desc = ""
            if getattr(item, "fields", None):
                desc = item.fields.get("System.Description", "")
            # Detect whether the description appears to be HTML (Azure DevOps stores HTML)
            fmt = "markdown"
            try:
                if isinstance(desc, str) and re.search(r"<[^>]+>", desc):
                    fmt = "html"
            except Exception:
                fmt = "markdown"

            # Log successful retrieval
            self.log.log_msg(
                "INFO",
                f"Loaded description for work item {work_item_id} (format: {fmt})",
            )
            return (True, desc, fmt)
        except Exception as e:
            self.log.log_msg("ERROR", f"Error fetching work item {work_item_id}: {e}")
            return (False, f"Error fetching work item {work_item_id}: {e}")

    def update_work_item_description(
        self, work_item_id: int, description: str, markdown: bool = False
    ):
        """Update the System.Description field of a work item.

        Returns (True, message) on success; (False, message) on failure.
        """
        try:
            patch_document = [
                {
                    "op": "add",
                    "path": "/fields/System.Description",
                    "value": description,
                }
            ]
            if markdown:
                # Mark the Description field as Markdown formatted in Azure DevOps
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/multilineFieldsFormat/System.Description",
                        "value": "Markdown",
                    }
                )
            self.wit_client.update_work_item(
                patch_document, int(work_item_id), project=self.project_name
            )
            self.log.log_msg(
                "INFO", f"Updated description for work item {work_item_id}"
            )
            return (True, f"Updated description for work item {work_item_id}")
        except AzureDevOpsServiceError as e:
            self.log.log_msg("ERROR", f"Azure DevOps error occurred: {e}")
            return (False, f"Azure DevOps error occurred: {e}")
        except Exception as e:
            self.log.log_msg("ERROR", f"Error updating work item {work_item_id}: {e}")
            return (False, f"Error updating work item {work_item_id}: {e}")

    def update_work_item_fields(
        self, work_item_id: int, fields: dict, markdown: bool = False
    ):
        """Update multiple fields of a work item.
        
        Args:
            work_item_id: ID of the work item to update
            fields: Dictionary of field names to values (e.g., {"System.State": "Active"})
            markdown: Whether to format System.Description as markdown
            
        Returns (True, message) on success; (False, message) on failure.
        """
        try:
            patch_document = []
            
            # Add each field to the patch document
            for field_name, value in fields.items():
                if value is not None and value != "":
                    patch_document.append({
                        "op": "add",
                        "path": f"/fields/{field_name}",
                        "value": value,
                    })
            
            # If updating description and markdown is True, set the format
            if markdown and "System.Description" in fields:
                patch_document.append({
                    "op": "add",
                    "path": "/multilineFieldsFormat/System.Description",
                    "value": "Markdown",
                })
            
            # Only proceed if there are fields to update
            if not patch_document:
                return (True, f"No changes needed for work item {work_item_id}")
            
            self.wit_client.update_work_item(
                patch_document, int(work_item_id), project=self.project_name
            )
            
            field_names = list(fields.keys())
            self.log.log_msg(
                "INFO", f"Updated fields {field_names} for work item {work_item_id}"
            )
            return (True, f"Updated work item {work_item_id} successfully")
            
        except AzureDevOpsServiceError as e:
            self.log.log_msg("ERROR", f"Azure DevOps error occurred: {e}")
            return (False, f"Azure DevOps error occurred: {e}")
        except Exception as e:
            self.log.log_msg("ERROR", f"Error updating work item {work_item_id}: {e}")
            return (False, f"Error updating work item {work_item_id}: {e}")

    def get_work_item_details(self, work_item_id: int):
        """Get work item details including state, assigned to, and priority.
        
        Returns (True, details_dict) on success; (False, error_message) on failure.
        """
        try:
            work_item = self.wit_client.get_work_item(int(work_item_id), project=self.project_name)
            
            # Extract assigned to field with better handling
            assigned_to_field = work_item.fields.get("System.AssignedTo")
            assigned_to = ""
            if assigned_to_field:
                if isinstance(assigned_to_field, dict):
                    # It's a user object with displayName, uniqueName, etc.
                    assigned_to = assigned_to_field.get("displayName", assigned_to_field.get("uniqueName", ""))
                elif isinstance(assigned_to_field, str):
                    # It's just a string
                    assigned_to = assigned_to_field
            
            # Extract priority with better handling
            priority_field = work_item.fields.get("Microsoft.VSTS.Common.Priority")
            priority = None
            if priority_field is not None:
                try:
                    priority = int(priority_field)
                except (ValueError, TypeError):
                    priority = None
            
            details = {
                "state": work_item.fields.get("System.State"),
                "assigned_to": assigned_to,
                "assigned_to_raw": assigned_to_field,  # Keep raw field for email extraction
                "priority": priority,
                "title": work_item.fields.get("System.Title"),
                "description": work_item.fields.get("System.Description", ""),
            }
            
            self.log.log_msg("INFO", f"Loaded details for work item {work_item_id}")
            return (True, details)
            
        except Exception as e:
            self.log.log_msg("ERROR", f"Error fetching work item details {work_item_id}: {e}")
            return (False, f"Error fetching work item details {work_item_id}: {e}")

    # DevOpsManager should not itself implement update logic; calls go to DevOpsClient
