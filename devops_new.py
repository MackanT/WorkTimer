from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v7_1.work_item_tracking.models import CommentCreate
from azure.devops.exceptions import AzureDevOpsServiceError
import pandas as pd


class DevOpsManager:
    def __init__(self, df):
        self.clients = {}
        for _, row in df.iterrows():
            if row["org_url"].lower() in ["", "none", "null"] or row[
                "pat_token"
            ].lower() in ["", "none", "null"]:
                continue
            org_url = f"https://dev.azure.com/{row['org_url']}"
            client = DevOpsClient(row["pat_token"], org_url)
            try:
                client.connect()
                self.clients[row["customer_name"]] = client
            except Exception as e:
                print(f"DevOps connection failed for {row['customer_name']}: {e}")

    def save_comment(self, customer_name, comment, git_id):
        client = self.clients.get(customer_name)
        if not client:
            return f"No DevOps connection for {customer_name}"
        return client.add_comment_to_work_item(git_id, comment)

    def get_workitem_level(self, customer_name, level=None, work_item_id=None):
        client = self.clients.get(customer_name)
        if not client:
            return f"No DevOps connection for {customer_name}"
        return client.get_workitem_level(level, work_item_id)

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
            return (False, f"No DevOps connection for {customer_name}")
        return client.create_user_story(
            title, description, additional_fields, markdown, parent
        )

    def get_epics_feature_df(self):
        epics = []
        features = []
        for customer_name, client in self.clients.items():
            status, epic_items = client.get_workitem_level("Epic", return_full=True)
            status_f, feature_items = client.get_workitem_level(
                "Feature", return_full=True
            )
            epic_id_title_map = {}
            if status and epic_items:
                for epic in epic_items:
                    epic_id = getattr(epic, "id", None)
                    epic_title = getattr(epic, "fields", {}).get("System.Title", None)
                    epics.append(
                        {
                            "customer_name": customer_name,
                            "epic_id": epic_id,
                            "epic_title": epic_title,
                        }
                    )
                    epic_id_title_map[epic_id] = epic_title
            if status_f and feature_items:
                for feature in feature_items:
                    feature_id = getattr(feature, "id", None)
                    feature_title = getattr(feature, "fields", {}).get(
                        "System.Title", None
                    )
                    parent_epic_id = None
                    for rel in getattr(feature, "relations", []):
                        if (
                            getattr(rel, "rel", None)
                            == "System.LinkTypes.Hierarchy-Reverse"
                        ):
                            url = getattr(rel, "url", None)
                            if url:
                                try:
                                    parent_epic_id = int(url.rstrip("/").split("/")[-1])
                                except Exception:
                                    parent_epic_id = None
                    features.append(
                        {
                            "customer_name": customer_name,
                            "feature_id": feature_id,
                            "feature_title": feature_title,
                            "parent_epic_id": parent_epic_id,
                            "parent_epic_title": epic_id_title_map.get(parent_epic_id),
                        }
                    )
        epic_df = pd.DataFrame(epics)
        feature_df = pd.DataFrame(features)
        combined_df = feature_df.merge(
            epic_df,
            left_on=["customer_name", "parent_epic_id"],
            right_on=["customer_name", "epic_id"],
            how="right",
        )
        # Fill missing feature columns for epics without features
        for col in ["feature_id", "feature_title"]:
            if col not in combined_df.columns:
                combined_df[col] = None
        # Drop parent_epic_id and parent_epic_title columns if present
        combined_df = combined_df.drop(
            columns=[
                c
                for c in ["parent_epic_id", "parent_epic_title"]
                if c in combined_df.columns
            ]
        )
        return (True, combined_df)


class DevOpsClient:
    def __init__(self, personal_access_token, organization_url):
        self.personal_access_token = personal_access_token
        self.organization_url = organization_url

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
                raise Exception(
                    "Your Personal Access Token has expired or been revoked. Please renew it."
                )
            else:
                raise Exception(f"Failed to connect to Azure DevOps: {e}")

    def get_work_item_tracking_client(self):
        if not self.connection:
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
                return (False, f"Work item with ID {work_item_id} does not exist.")
            else:
                return (False, f"Azure DevOps error occurred: {e}")
        return (True, "Comment added successfully.")

    def get_workitem_level(
        self, level: str = None, work_item_id: int = None, return_full=False
    ):
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
            items = self.wit_client.get_work_items(ids, expand="All")
            if work_item_id:
                # Return the title of the single work item
                title = items[0].fields.get("System.Title", None)
                if title:
                    return (True, title)
                else:
                    return (False, "Title not found for work item.")
            else:
                if return_full:
                    return (True, items)
                epic_list = [
                    f"{item.id} - {item.fields['System.Title']}" for item in items
                ]
                return (True, epic_list)
        except Exception as e:
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
            return (True, f"Created User Story with ID {work_item.id}")
        except AzureDevOpsServiceError as e:
            return (False, f"Azure DevOps error occurred: {e}")
        except Exception as e:
            return (False, f"Error creating user story: {e}")
