"""Azure DevOps tracker module.

`AzureDevOpsProvider` adapts the historical `AzureDevOpsClient`
(src/tracker_manager.py) to the `TrackerProvider` contract. The Azure-specific
knowledge that used to live in `TrackerManager` — org-URL building, `System.*`
field mapping, PAT-signed attachment fetches — lives here now, so the manager
stays provider-neutral.

Kept as a subclass rather than a file move so the battle-tested client code
(and its imports in tests) stays put; a future cosmetic pass can relocate it.
"""

import html as _html
import re

import pandas as pd
import requests

from .base import TrackerCapabilities, TrackerProvider, WORK_ITEM_COLUMNS
from .process import AGILE
from .registry import register_provider
from ..tracker_manager import AzureDevOpsClient

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _plain_text(value, limit: int = 2000) -> str:
    """Searchable plain text from an HTML/markdown description: tags stripped,
    entities unescaped, whitespace collapsed, truncated to keep the cache lean."""
    if not value:
        return ""
    text = _TAG_RE.sub(" ", str(value))
    text = _html.unescape(text)
    return _WS_RE.sub(" ", text).strip()[:limit]


def _blankish(val) -> bool:
    """True for None/NaN/''/'none'/'null' — the sentinels stored for 'no value'."""
    if val is None:
        return True
    try:
        if pd.isna(val):
            return True
    except (TypeError, ValueError):
        pass
    return str(val).strip().lower() in ("", "none", "null", "nan")


@register_provider
class AzureDevOpsProvider(AzureDevOpsClient, TrackerProvider):
    """One customer's Azure DevOps connection, as a pluggable tracker module."""

    provider_key = "devops"
    display_name = "Azure DevOps"

    @classmethod
    def type_hierarchy(cls) -> tuple:
        """The class default (Agile); each project's own: process(project)."""
        return AGILE.types

    @classmethod
    def capabilities(cls) -> TrackerCapabilities:
        return TrackerCapabilities(
            board_columns=True, hierarchy=True, comments=True, attachments=True,
            branches=True,
        )

    @classmethod
    def from_customer_row(cls, row, log):
        """Build from a customers row (pat_token + org_url [+ tracker_project]).
        Returns None when credentials are missing — the manager skips those."""
        pat = row.get("pat_token")
        org = row.get("org_url")
        if _blankish(pat) or _blankish(org):
            return None
        extra = row.get("extra_tracker_projects")
        provider = cls(
            str(pat),
            f"https://dev.azure.com/{str(org).strip()}",
            log,
            project_name=row.get("tracker_project"),
            extra_projects=list(extra) if isinstance(extra, (list, tuple)) else [],
        )
        provider.customer_name = str(row.get("customer_name") or "")
        return provider

    # ── data ──────────────────────────────────────────────────────────────
    def fetch_work_items(self, min_id=None, min_changed_date=None):
        """Fetch this customer's work items on its projects' backlog levels
        (tasks included) as the canonical work-item DataFrame
        (WORK_ITEM_COLUMNS schema)."""
        status, items = self.get_workitem_level(
            level=None, return_full=True, min_id=min_id,
            min_changed_date=min_changed_date,
        )
        if not status or not items:
            return pd.DataFrame(columns=WORK_ITEM_COLUMNS)

        def _assigned_to(fields):
            af = fields.get("System.AssignedTo")
            if not af:
                return ""
            if isinstance(af, dict):
                return af.get("displayName", af.get("uniqueName", ""))
            return str(af)

        rows = []
        for item in items:
            fields = getattr(item, "fields", {}) or {}
            wtype = fields.get("System.WorkItemType")
            project = fields.get("System.TeamProject")
            process = self.process(project)
            if process.level_of(wtype) is None:
                continue
            if project:
                self._project_of[int(item.id)] = project
            rows.append(
                {
                    "customer_name": self.customer_name,
                    "type": wtype,
                    "id": item.id,
                    "title": fields.get("System.Title"),
                    "state": fields.get("System.State"),
                    "parent_id": (None if wtype in process.root_types
                                  else fields.get("System.Parent")),
                    "board_column": fields.get("System.BoardColumn", ""),
                    "board_column_done": int(bool(fields.get("System.BoardColumnDone", False))),
                    "assigned_to": _assigned_to(fields),
                    "changed_date": fields.get("System.ChangedDate", ""),
                    "priority": fields.get("Microsoft.VSTS.Common.Priority"),
                    # Already in the expand="All" payload — cached as plain text
                    # so board search / palette find can match description bodies.
                    "description": _plain_text(fields.get("System.Description")),
                    "project": project,
                }
            )
        if not rows:
            return pd.DataFrame(columns=WORK_ITEM_COLUMNS)
        return pd.DataFrame(rows, columns=WORK_ITEM_COLUMNS)

    # ── mutations ─────────────────────────────────────────────────────────
    def create_item(
        self, type_key, title, description=None, additional_fields=None,
        markdown=False, parent=None, project=None,
    ):
        """Create a work item of `type_key` in `project` (default: the main
        one) — the root level takes no parent."""
        if type_key in self.process(project).root_types:
            parent = None
        return self._create_work_item(
            type_key, title, description, additional_fields, markdown, parent, project)

    # ── attachments ───────────────────────────────────────────────────────
    def owns_attachment_url(self, url) -> bool:
        return self.owned_url(url, self.organization_url, contains="/_apis/wit/attachments/")

    def fetch_attachment(self, url):
        """Fetch an owned attachment with this org's PAT. (bytes, ctype) or None."""
        try:
            resp = requests.get(
                url, auth=("", self.personal_access_token), timeout=20
            )
            if resp.ok:
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                return resp.content, ctype
        except Exception as e:
            self.log.error(f"Attachment fetch failed ({self.organization_url}): {e}")
        return None
