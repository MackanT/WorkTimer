"""The tracker-provider contract.

A provider wraps one customer's connection to one issue tracker (Azure DevOps,
Jira, ...). The app consumes providers only through `DevOpsManager`, which
multiplexes per customer — so a provider never needs to know about any other
customer or provider.

The load-bearing contract is `fetch_work_items()`: it must return a DataFrame
with exactly the `WORK_ITEM_COLUMNS` schema. Everything downstream (the board,
hierarchy, search, work-item pickers, reports) renders from that frame.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

# Canonical work-item DataFrame schema — the contract every provider's
# fetch_work_items() must satisfy. Types: id/parent_id numeric (parent_id may
# be None/NaN), board_column_done 0/1 int, the rest strings (priority may be
# a numeric or None).
WORK_ITEM_COLUMNS = [
    "customer_name",
    "type",
    "id",
    "title",
    "state",
    "parent_id",
    "board_column",
    "board_column_done",
    "assigned_to",
    "changed_date",
    "priority",
    "description",  # plain-text (tags stripped, truncated) — for search only
]

# Work-item levels root → leaf. Used as the fallback wherever no provider is
# connected (e.g. rendering the board type chips before any data loads).
DEFAULT_TYPE_HIERARCHY = ("Epic", "Feature", "User Story")

# Fallback state names where no provider can say better — matches the classic
# Azure DevOps Agile process the app's config historically assumed.
DEFAULT_STATE_OPTIONS = ("New", "Active", "Resolved", "Closed", "Removed")


@dataclass(frozen=True)
class TrackerCapabilities:
    """What a provider can do — lets the UI hide what a tracker can't offer
    instead of erroring (e.g. a provider with no board columns)."""

    board_columns: bool = True   # has a column-based board (drag-drop moves)
    hierarchy: bool = True       # parent/child work-item levels
    comments: bool = True        # read + post work-item comments
    attachments: bool = True     # upload/fetch attachments (image embedding)
    # Attachments live on an ITEM, not the project (Jira) — image upload is
    # only offered where a work item already exists (the update dialog).
    attachments_require_item: bool = False
    # False when state and board column are the SAME axis (Jira: status is
    # the column) — the UI then hides the redundant board-column input.
    distinct_board_column: bool = True


class TrackerProvider(ABC):
    """One customer's connection to one issue tracker.

    Concrete providers set `provider_key`, register themselves via
    `registry.register_provider`, and implement the abstract methods. Method
    names intentionally match the historical DevOpsClient surface so the Azure
    provider implements most of this by inheritance.
    """

    # Registry key, matched against customers.integration_type (e.g. "devops").
    provider_key: str = ""

    # Human name for UI labels ("Open in Azure DevOps" / "Open in Jira").
    display_name: str = "Tracker"

    # Set by from_customer_row(); included in fetch_work_items() output.
    customer_name: str = ""

    # Populated by connect(); feeds the customer form's project picker.
    available_projects: list = []

    # ── identity / classification ─────────────────────────────────────────
    @classmethod
    def type_hierarchy(cls) -> tuple:
        """Work-item levels root → leaf (e.g. Epic, Feature, User Story)."""
        return DEFAULT_TYPE_HIERARCHY

    @classmethod
    def capabilities(cls) -> TrackerCapabilities:
        return TrackerCapabilities()

    @classmethod
    def preferred_type(cls) -> str:
        """The default working level for boards — usually the leaf (e.g.
        User Story), but a provider whose leaf is auxiliary (Jira's Sub-task)
        can point at the level people actually work at."""
        return cls.type_hierarchy()[-1]

    def list_members(self):
        """(True, [display names]) of people usable as assignees on this
        connection, or (False, msg). Default: not supported."""
        return (False, "Member listing is not supported for this tracker")

    def state_options(self) -> list:
        """State names for this tracker's work items, offered by the State
        dropdowns. Instance-level (may need a live call, e.g. Jira statuses);
        the default list matches the app's historical Azure config."""
        return list(DEFAULT_STATE_OPTIONS)

    @classmethod
    @abstractmethod
    def from_customer_row(cls, row, log):
        """Build an (unconnected) provider from a customers-table row, or None
        when the row lacks the credentials this provider needs."""

    # ── connection ────────────────────────────────────────────────────────
    @abstractmethod
    def connect(self):
        """Open/validate the connection; populate available_projects. Raises
        on failure (the manager logs and skips the customer)."""

    # ── data ──────────────────────────────────────────────────────────────
    @abstractmethod
    def fetch_work_items(self, min_id=None, min_changed_date=None):
        """Return a DataFrame in the WORK_ITEM_COLUMNS schema. `min_id` /
        `min_changed_date` support incremental refresh (only newer/edited
        items); both None means a full fetch."""

    @abstractmethod
    def get_work_item_description(self, work_item_id):
        """(status, description_or_error, format, live_fields) 4-tuple."""

    @abstractmethod
    def get_work_item_url(self, work_item_id):
        """The tracker's web URL for a work item, or None."""

    # ── mutations ─────────────────────────────────────────────────────────
    @abstractmethod
    def create_item(
        self, type_key, title, description=None, additional_fields=None,
        markdown=False, parent=None,
    ):
        """Create a work item of `type_key` (a value from type_hierarchy()).
        Returns (status, payload)."""

    @abstractmethod
    def update_work_item_fields(self, work_item_id, fields, markdown=False):
        """Update fields of a work item. Returns (status, msg)."""

    @abstractmethod
    def set_board_column(self, work_item_id, column_name):
        """Move a work item to a board column. Returns (status, msg)."""

    # ── comments ──────────────────────────────────────────────────────────
    @abstractmethod
    def add_comment_to_work_item(self, work_item_id, comment_text):
        """Post a comment. Returns (status, msg)."""

    @abstractmethod
    def get_work_item_comments(self, work_item_id):
        """(True, [{author, date, text}, ...]) or (False, msg)."""

    # ── attachments ───────────────────────────────────────────────────────
    @abstractmethod
    def upload_attachment(self, file_name, content, work_item_id=None):
        """Upload bytes; return an embeddable URL or None. `work_item_id`
        targets item-scoped stores (Jira); project-scoped ones ignore it."""

    @abstractmethod
    def owns_attachment_url(self, url) -> bool:
        """True when `url` is an attachment URL served by this provider's
        backend (used to route proxy fetches and as an SSRF guard)."""

    @abstractmethod
    def fetch_attachment(self, url):
        """Fetch an owned attachment's bytes. (content, content_type) or None."""
