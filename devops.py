from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v7_1.work_item_tracking.models import CommentCreate
from azure.devops.exceptions import AzureDevOpsServiceError


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
                return f"Work item with ID {work_item_id} does not exist."
            else:
                return f"Azure DevOps error occurred: {e}"

        return None


# # Define the work item fields
# work_item = [
#     {"op": "add", "path": "/fields/System.Title", "value": "Sample Task"},
#     {
#         "op": "add",
#         "path": "/fields/System.Description",
#         "value": "This is a sample task created via the Azure DevOps Python API.",
#     },
# ]

# # Create the work item
# project = "YOUR_PROJECT_NAME"
# work_item_type = "Task"
# created_work_item = wit_client.create_work_item(
#     document=work_item, project=project, type=work_item_type
# )

# # Print the created work item details
# pprint.pprint(created_work_item)

# alter table customers add column sort_order integer default = 0
