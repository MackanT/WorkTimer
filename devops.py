from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v7_1.work_item_tracking.models import JsonPatchOperation
from azure.devops.exceptions import AzureDevOpsServiceError


class DevOpsClient:
    def __init__(self, personal_access_token, organization_url):
        self.personal_access_token = personal_access_token
        self.organization_url = organization_url

    def connect(self):
        # Create a connection to the Azure DevOps organization
        credentials = BasicAuthentication("", self.personal_access_token)
        self.connection = Connection(base_url=self.organization_url, creds=credentials)

        self.wit_client = self.get_work_item_tracking_client()

    def get_work_item_tracking_client(self):
        if not self.connection:
            raise Exception("Connection not established. Call connect() first.")
        return self.connection.clients.get_work_item_tracking_client()

    def add_comment_to_work_item(self, work_item_id, comment_text):
        # Create a patch document to add a comment
        patch_document = [
            JsonPatchOperation(
                op="add", path="/fields/System.History", value=comment_text
            )
        ]

        try:
            updated_item = self.wit_client.update_work_item(
                document=patch_document, id=work_item_id
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
        # print(f"Updated work item {updated_item.id} with new comment.")


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
