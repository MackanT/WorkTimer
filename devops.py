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

    def get_epics_feature_df(self):
        rows = []
        for customer_name, client in self.clients.items():
            status, items = client.get_workitem_level(level=None, return_full=True)
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

            # Build parent relationships
            feature_to_epic = {}
            for feature in features.values():
                parent_id = feature.fields.get("System.Parent")
                if parent_id in epics:
                    feature_to_epic[feature.id] = parent_id

            user_story_to_feature = {}
            for us in user_stories.values():
                parent_id = us.fields.get("System.Parent")
                if parent_id in features:
                    user_story_to_feature[us.id] = parent_id

            # Build rows for each user story, feature, epic
            for us_id, us in user_stories.items():
                feature_id = user_story_to_feature.get(us_id)
                feature = features.get(feature_id)
                epic_id = feature_to_epic.get(feature_id) if feature_id else None
                epic = epics.get(epic_id)
                rows.append(
                    {
                        "customer_name": customer_name,
                        "epic_id": epic.id if epic else None,
                        "epic_title": epic.fields.get("System.Title") if epic else None,
                        "epic_state": epic.fields.get("System.State") if epic else None,
                        "feature_id": feature.id if feature else None,
                        "feature_title": feature.fields.get("System.Title")
                        if feature
                        else None,
                        "feature_state": feature.fields.get("System.State")
                        if feature
                        else None,
                        "user_story_id": us.id,
                        "user_story_title": us.fields.get("System.Title"),
                        "user_story_state": us.fields.get("System.State"),
                    }
                )
            # Add features without user stories
            for feature_id, feature in features.items():
                if feature_id not in user_story_to_feature.values():
                    epic_id = feature_to_epic.get(feature_id)
                    epic = epics.get(epic_id)
                    rows.append(
                        {
                            "customer_name": customer_name,
                            "epic_id": epic.id if epic else None,
                            "epic_title": epic.fields.get("System.Title")
                            if epic
                            else None,
                            "epic_state": epic.fields.get("System.State")
                            if epic
                            else None,
                            "feature_id": feature.id,
                            "feature_title": feature.fields.get("System.Title"),
                            "feature_state": feature.fields.get("System.State"),
                            "user_story_id": None,
                            "user_story_title": None,
                            "user_story_state": None,
                        }
                    )
            # Add epics without features
            for epic_id, epic in epics.items():
                if epic_id not in feature_to_epic.values():
                    rows.append(
                        {
                            "customer_name": customer_name,
                            "epic_id": epic.id,
                            "epic_title": epic.fields.get("System.Title"),
                            "epic_state": epic.fields.get("System.State"),
                            "feature_id": None,
                            "feature_title": None,
                            "feature_state": None,
                            "user_story_id": None,
                            "user_story_title": None,
                            "user_story_state": None,
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
        self, level: str = None, work_item_id: int = None, return_full=False
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

    # DevOpsManager should not itself implement update logic; calls go to DevOpsClient
