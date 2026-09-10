from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v7_1.work_item_tracking.models import CommentCreate
from azure.devops.v7_1.work.models import TeamContext
from azure.devops.exceptions import AzureDevOpsServiceError
import pandas as pd
import io
import re
import requests
import base64
import json


def _clean_project(val):
    """Normalise a stored devops_project value to a non-empty str, or None.
    Guards against pandas NaN and the string sentinels used elsewhere."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    return s if s and s.lower() not in ("none", "null", "nan") else None


def _choose_project(configured, available):
    """Pick which project a client uses: the configured one if it exists in the
    org, else the first available (today's default), else None."""
    configured = _clean_project(configured)
    if configured and configured in available:
        return configured
    return available[0] if available else None


class DevOpsManager:
    """Provider-neutral multiplexer: one TrackerProvider per customer.

    Which provider a customer gets is resolved from the customers table's
    `integration_type` column via the tracker registry (default: Azure DevOps).
    Kept under its historical name — the app-facing API is unchanged.
    """

    def __init__(self, df, log):
        # Imported here, not at module top: provider modules import this module
        # (the Azure provider subclasses DevOpsClient below), so a top-level
        # import would be circular.
        from .trackers.registry import create_provider_for_row

        self.clients = {}
        self.log = log
        for _, row in df.iterrows():
            client = create_provider_for_row(row, self.log)
            if client is None:
                continue  # missing credentials or unknown provider (logged)
            try:
                client.connect()
                self.clients[row["customer_name"]] = client
                self.log.info(
                    f"Connected to {client.provider_key} tracker for customer "
                    f"{row['customer_name']}"
                )
            except Exception as e:
                self.log.error(
                    f"Tracker connection failed for {row['customer_name']}:\n{e}"
                )

    def _get_client(self, customer_name):
        """
        Get DevOps client for customer, logging warning if not found.

        Returns:
            DevOpsClient or None
        """
        client = self.clients.get(customer_name)
        if not client:
            self.log.warning(f"No tracker connection for {customer_name}")
        return client

    def get_available_projects(self):
        """{customer_name: [project names in their org]} for connected clients."""
        return {
            name: list(client.available_projects)
            for name, client in self.clients.items()
        }

    def upload_attachment(self, customer_name, file_name, content):
        """Upload bytes as a DevOps attachment for a customer's project; returns
        the attachment URL or None."""
        client = self._get_client(customer_name)
        return client.upload_attachment(file_name, content) if client else None

    def fetch_attachment(self, url):
        """Fetch an attachment's bytes via whichever connected provider owns the
        URL, for proxying images into the WorkTimer preview. Returns
        (content, content_type) or None. Providers only accept their own
        backend's attachment URLs (SSRF guard)."""
        for client in self.clients.values():
            if client.owns_attachment_url(url):
                return client.fetch_attachment(url)
        return None

    def save_comment(self, customer_name, comment, git_id):
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}")
        return client.add_comment_to_work_item(git_id, comment)

    def get_workitem_level(self, customer_name, level=None, work_item_id=None):
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}")
        return client.get_workitem_level(level, work_item_id)

    def get_description(self, customer_name, work_item_id):
        """Return the work item's description plus live scalar fields.

        Always returns a 4-tuple: (status, description_or_error, format, live_fields).
        """
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}", "markdown", {})
        return client.get_work_item_description(work_item_id)

    def get_comments(self, customer_name, work_item_id):
        """Return a work item's comments. (True, [ {author,date,text}, ... ]) or (False, msg)."""
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}")
        return client.get_work_item_comments(work_item_id)

    def get_work_item_url(self, customer_name, work_item_id):
        """Return the Azure DevOps web URL for a work item, or None."""
        client = self._get_client(customer_name)
        if not client:
            return None
        return client.get_work_item_url(work_item_id)

    def update_work_item_fields(
        self, customer_name, work_item_id, fields, markdown=False
    ):
        """Update multiple fields of a work item. Returns (True, msg) or (False, msg)."""
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}")
        return client.update_work_item_fields(work_item_id, fields, markdown)

    def create_user_story(
        self,
        customer_name,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}")
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
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}")
        return client.create_epic(title, description, additional_fields, markdown)

    def create_feature(
        self,
        customer_name,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}")
        return client.create_feature(
            title, description, additional_fields, markdown, parent
        )

    def create_item(
        self,
        customer_name,
        type_key,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        """Create a work item of `type_key` (a value from the provider's
        type_hierarchy()). Provider-neutral generic behind the named wrappers."""
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}")
        return client.create_item(
            type_key, title, description, additional_fields, markdown, parent
        )

    def get_epics_feature_df(self, max_ids: dict = None, changed_dates: dict = None):
        """All customers' work items in the canonical WORK_ITEM_COLUMNS shape.

        Field mapping lives in each provider's fetch_work_items() — this just
        concatenates per-customer frames.

        Args:
            max_ids: Dict of {customer_name: max_id} for incremental refresh (new items)
            changed_dates: Dict of {customer_name: iso_datetime_str} for catching edits
        """
        frames = []
        for customer_name, client in self.clients.items():
            # One provider's failure must never abort the whole preload — that
            # would blank every customer's board, not just the broken one.
            try:
                df = client.fetch_work_items(
                    min_id=max_ids.get(customer_name) if max_ids else None,
                    min_changed_date=(
                        changed_dates.get(customer_name) if changed_dates else None
                    ),
                )
            except Exception as e:
                self.log.error(f"Work-item fetch failed for {customer_name}: {e}")
                continue
            if df is not None and not df.empty:
                frames.append(df)

        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame([])
        return (True, df)

    def set_board_column(
        self, customer_name: str, work_item_id: int, column_name: str
    ) -> tuple:
        """Move a work item to a board column."""
        client = self._get_client(customer_name)
        if not client:
            return (False, f"No tracker connection for {customer_name}")
        return client.set_board_column(work_item_id, column_name)


class DevOpsClient:
    def __init__(
        self, personal_access_token, organization_url, log, project_name=None
    ):
        self.personal_access_token = personal_access_token
        self.organization_url = organization_url
        self.log = log
        self.connection = None
        # User-selected project for this customer (None = auto: first project).
        self.configured_project = _clean_project(project_name)
        # All project names in the org, cached at connect() for the picker.
        self.available_projects = []

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

            # List all projects (also validates the connection) so the user can
            # pick which one this customer uses; default to the first.
            projects = list(core_client.get_projects())
            if not projects:
                raise Exception("No projects found in the Azure DevOps organization.")
            self.available_projects = [p.name for p in projects]
            chosen = _choose_project(self.configured_project, self.available_projects)
            if self.configured_project and chosen != self.configured_project:
                self.log.warning(
                    f"Configured DevOps project '{self.configured_project}' not found "
                    f"in {self.organization_url}; using '{chosen}'"
                )
            self.project_name = chosen

        except Exception as e:
            msg = str(e).lower()
            if "expired" in msg or "revoked" in msg or "unauthorized" in msg:
                self.log.error(
                    "Your Personal Access Token has expired or been revoked. Please renew it."
                )
                raise Exception(
                    "Your Personal Access Token has expired or been revoked. Please renew it."
                )
            else:
                self.log.error(f"Failed to connect to Azure DevOps: {e}")
                raise Exception(f"Failed to connect to Azure DevOps: {e}")

    def get_work_item_tracking_client(self):
        if not self.connection:
            self.log.error("Connection not established. Call connect() first.")
            raise Exception("Connection not established. Call connect() first.")
        return self.connection.clients.get_work_item_tracking_client()

    def upload_attachment(self, file_name, content):
        """Upload `content` (bytes) as a project attachment and return its URL,
        which can be embedded in a work-item description (e.g. ![](url)). Returns
        None on failure."""
        try:
            # create_attachment streams via data.read(), so it needs a file-like
            # object — wrap the raw bytes in BytesIO.
            ref = self.wit_client.create_attachment(
                upload_stream=io.BytesIO(content),
                project=self.project_name,
                file_name=file_name,
            )
            return ref.url
        except Exception as e:
            self.log.error(f"Failed to upload attachment '{file_name}': {e}")
            return None

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
                self.log.warning(f"Work item with ID {work_item_id} does not exist.")
                return (False, f"Work item with ID {work_item_id} does not exist.")
            else:
                self.log.error(f"Azure DevOps error occurred: {e}")
                return (False, f"Azure DevOps error occurred: {e}")
        except Exception as e:
            self.log.error(f"Error adding comment to work item {work_item_id}: {e}")
            return (False, f"Error adding comment to work item {work_item_id}: {e}")
        return (True, "Comment added successfully.")

    def get_workitem_level(
        self,
        level: str = None,
        work_item_id: int = None,
        return_full=False,
        min_id: int = None,
        min_changed_date: str = None,
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
        def _date_only(dt_str: str) -> str:
            return dt_str[:10] if dt_str else dt_str
        if min_id is not None and min_changed_date:
            query += f" AND ([System.Id] > {min_id} OR [System.ChangedDate] > '{_date_only(min_changed_date)}')"
        elif min_id is not None:
            query += f" AND [System.Id] > {min_id}"
        elif min_changed_date:
            query += f" AND [System.ChangedDate] > '{_date_only(min_changed_date)}'"
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
            self.log.error(f"Error fetching work items: {e}")
            return (False, f"Error fetching work items: {e}")

    def get_work_item_comments(self, work_item_id: int):
        """Return a work item's comments, oldest first.

        Returns (True, [ {author, date, text}, ... ]) or (False, message).
        """
        try:
            result = self.wit_client.get_comments(
                project=self.project_name, work_item_id=int(work_item_id)
            )
            raw = getattr(result, "comments", None) or []

            def _author(created_by):
                if isinstance(created_by, dict):
                    return created_by.get("displayName") or created_by.get("uniqueName") or ""
                return (
                    getattr(created_by, "display_name", None)
                    or getattr(created_by, "unique_name", None)
                    or ""
                )

            comments = [
                {
                    "author": _author(getattr(c, "created_by", None)),
                    "date": str(getattr(c, "created_date", "") or ""),
                    "text": getattr(c, "text", "") or "",
                }
                for c in raw
            ]
            # Newest first (ISO dates sort lexically).
            comments.sort(key=lambda c: c["date"], reverse=True)
            self.log.info(f"Loaded {len(comments)} comments for work item {work_item_id}")
            return (True, comments)
        except Exception as e:
            self.log.error(f"Error fetching comments for {work_item_id}: {e}")
            return (False, f"Error fetching comments: {e}")

    def get_work_item_url(self, work_item_id: int) -> str:
        """Build the Azure DevOps web URL for a work item."""
        return f"{self.organization_url}/{self.project_name}/_workitems/edit/{int(work_item_id)}"

    def _create_work_item(
        self,
        work_item_type: str,
        title: str,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        """
        Create a work item in Azure DevOps.

        Args:
            work_item_type: "User Story", "Epic", or "Feature"
            title: Work item title
            description: Optional description
            additional_fields: Dict of additional field values
            markdown: Whether description is markdown format
            parent: Parent work item ID (for Features and User Stories)

        Returns:
            Tuple of (success: bool, message: str)
        """
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
                            {
                                "op": "add",
                                "path": f"/fields/{field}",
                                "value": value,
                            }
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
                patch_document, project=self.project_name, type=work_item_type
            )

            self.log.info(f"Created {work_item_type} with ID {work_item.id}")
            return (True, f"Created {work_item_type} with ID {work_item.id}")

        except AzureDevOpsServiceError as e:
            self.log.error(f"Azure DevOps error occurred: {e}")
            return (False, f"Azure DevOps error occurred: {e}")
        except Exception as e:
            self.log.error(f"Error creating {work_item_type.lower()}: {e}")
            return (False, f"Error creating {work_item_type.lower()}: {e}")

    def create_user_story(
        self,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        """Create a new User Story work item in Azure DevOps."""
        return self._create_work_item(
            "User Story", title, description, additional_fields, markdown, parent
        )

    def create_epic(
        self,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
    ):
        """Create a new Epic work item in Azure DevOps."""
        return self._create_work_item(
            "Epic", title, description, additional_fields, markdown
        )

    def create_feature(
        self,
        title,
        description=None,
        additional_fields=None,
        markdown=False,
        parent=None,
    ):
        """Create a new Feature work item in Azure DevOps."""
        return self._create_work_item(
            "Feature", title, description, additional_fields, markdown, parent
        )

    def get_work_item_description(self, work_item_id: int):
        """Return the System.Description field for a single work item as plain text.

        Always returns a 4-tuple: (status, description_or_error, format, live_fields).
        """
        try:
            item = self.wit_client.get_work_item(int(work_item_id), expand="All")
            fields = getattr(item, "fields", {}) or {}
            desc = fields.get("System.Description", "")

            # Detect whether the description appears to be HTML (Azure DevOps stores HTML)
            fmt = "markdown"
            try:
                if isinstance(desc, str) and re.search(r"<[^>]+>", desc):
                    fmt = "html"
            except Exception:
                fmt = "markdown"

            # Extract the assigned_to display name
            af = fields.get("System.AssignedTo")
            if isinstance(af, dict):
                assigned_to = af.get("displayName", af.get("uniqueName", ""))
            else:
                assigned_to = str(af) if af else ""

            # Bundle all cacheable scalars so callers can update the local DB
            live_fields = {
                "board_column": fields.get("System.BoardColumn", ""),
                "board_column_done": int(bool(fields.get("System.BoardColumnDone", False))),
                "state": fields.get("System.State", ""),
                "assigned_to": assigned_to,
                "assigned_to_raw": af,
                "priority": fields.get("Microsoft.VSTS.Common.Priority"),
                "changed_date": fields.get("System.ChangedDate", ""),
            }

            self.log.info(
                f"Loaded description for work item {work_item_id} (format: {fmt})"
            )
            return (True, desc, fmt, live_fields)
        except Exception as e:
            self.log.error(f"Error fetching work item {work_item_id}: {e}")
            return (False, f"Error fetching work item {work_item_id}: {e}", "markdown", {})

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
                    patch_document.append(
                        {
                            "op": "add",
                            "path": f"/fields/{field_name}",
                            "value": value,
                        }
                    )

            # If updating description and markdown is True, set the format
            if markdown and "System.Description" in fields:
                patch_document.append(
                    {
                        "op": "add",
                        "path": "/multilineFieldsFormat/System.Description",
                        "value": "Markdown",
                    }
                )

            # Only proceed if there are fields to update
            if not patch_document:
                return (True, f"No changes needed for work item {work_item_id}")

            self.wit_client.update_work_item(
                patch_document, int(work_item_id), project=self.project_name
            )

            field_names = list(fields.keys())
            self.log.info(f"Updated fields {field_names} for work item {work_item_id}")
            return (True, f"Updated work item {work_item_id} successfully")

        except AzureDevOpsServiceError as e:
            self.log.error(f"Azure DevOps error occurred: {e}")
            return (False, f"Azure DevOps error occurred: {e}")
        except Exception as e:
            self.log.error(f"Error updating work item {work_item_id}: {e}")
            return (False, f"Error updating work item {work_item_id}: {e}")

    def set_board_column(self, work_item_id: int, column_name: str) -> tuple:
        """Move a work item to a board column via the hidden Kanban.Column field.

        System.BoardColumn is readonly, but the underlying WEF_xxx_Kanban.Column
        field is writable and moves the card on the board. The field name contains
        a hash unique to each org/project but always ends with 'Kanban.Column'.

        Returns (True, message) or (False, message).
        """
        try:
            token = base64.b64encode(
                f":{self.personal_access_token}".encode("ascii")
            ).decode("ascii")
            headers = {"Authorization": f"Basic {token}"}

            # Step 1 — fetch work item to find the Kanban.Column field name
            get_url = (
                f"{self.organization_url}/_apis/wit/workitems/{int(work_item_id)}"
                f"?api-version=7.1&$expand=fields"
            )
            get_resp = requests.get(get_url, headers=headers, timeout=30)
            if get_resp.status_code != 200:
                return (False, f"Could not fetch work item: {get_resp.text}")

            fields = get_resp.json().get("fields", {})

            # Find the Kanban.Column field — format: WEF_<hash>_Kanban.Column
            kanban_column_field = next(
                (k for k in fields if k.endswith("Kanban.Column")), None
            )
            kanban_done_field = next(
                (k for k in fields if k.endswith("Kanban.Column.Done")), None
            )

            if not kanban_column_field:
                # ADO only provisions the WEF_*_Kanban.Column fields once a team
                # board has picked the item up — new/API-created items lack them
                # until the board next loads (or the area path maps to no team).
                return (
                    False,
                    f"#{work_item_id} isn't on a team board yet (new items get "
                    "board fields when the board next loads) — open the board "
                    "in Azure DevOps once, or check the item's area path",
                )

            # Step 2 — patch the Kanban.Column field
            patch_document = [
                {
                    "op": "add",
                    "path": f"/fields/{kanban_column_field}",
                    "value": column_name,
                },
            ]
            if kanban_done_field:
                patch_document.append(
                    {
                        "op": "add",
                        "path": f"/fields/{kanban_done_field}",
                        "value": False,
                    }
                )

            patch_url = (
                f"{self.organization_url}/_apis/wit/workitems/{int(work_item_id)}"
                f"?api-version=7.1"
            )
            patch_resp = requests.patch(
                url=patch_url,
                headers={**headers, "Content-Type": "application/json-patch+json"},
                data=json.dumps(patch_document),
                timeout=30,
            )

            if patch_resp.status_code in (200, 201):
                actual = patch_resp.json().get("fields", {}).get("System.BoardColumn")
                self.log.info(
                    f"Moved work item {work_item_id} to '{column_name}' "
                    f"(board confirms: '{actual}')"
                )
                return (True, f"Moved work item {work_item_id} to '{column_name}'")
            else:
                try:
                    error_msg = patch_resp.json().get("message", patch_resp.text)
                except Exception:
                    error_msg = patch_resp.text or f"HTTP {patch_resp.status_code}"
                self.log.error(f"Board column update failed: {error_msg}")
                return (False, f"Error: {error_msg}")

        except Exception as e:
            self.log.error(f"Error moving work item to board column: {e}")
            return (False, f"Error: {e}")

    def get_board_columns_via_team_autodetect(self, board_type: str = None) -> tuple:
        """Fallback: auto-detect team and fetch columns via board API."""
        try:
            core_client = self.connection.clients.get_core_client()
            work_client = self.connection.clients.get_work_client()
            teams = core_client.get_teams(self.project_name)

            for t in teams:
                team_context = TeamContext(project=self.project_name, team=t.name)
                boards = work_client.get_boards(team_context)
                stories_board = next((b for b in boards if b.name == board_type), None)
                if not stories_board:
                    continue
                board_detail = work_client.get_board(team_context, stories_board.id)
                columns = [c.name for c in board_detail.columns]
                return (True, columns)

            return (False, f"No board '{board_type}' found in any team")
        except Exception as e:
            self.log.error(f"Fallback board column fetch failed: {e}")
            return (False, f"Error: {e}")

    # DevOpsManager should not itself implement update logic; calls go to DevOpsClient
