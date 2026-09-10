"""Jira Cloud tracker module (read-first v1).

`JiraProvider` implements the `TrackerProvider` contract against the Jira
Cloud REST API (v3). Scope of this first iteration:

  READ  — connect/validate, fetch work items into the canonical DataFrame
          (board, hierarchy, search, palette find and time-linking all work),
          issue descriptions (ADF → plain markdown-ish text), comments, URLs.
  WRITE — create / field updates / comments / board moves. The handler layer
          still speaks Azure field names (System.State, System.AssignedTo,
          Microsoft.VSTS.Common.Priority, System.Tags) — `_translate_fields`
          maps them. Board moves and state changes are workflow *transitions*
          in Jira; when the workflow forbids one, the move fails with the
          allowed targets listed. Descriptions are written as minimal ADF
          (paragraphs + line breaks) — saving over a richly-formatted Jira
          description flattens it. Attachments remain unsupported.

Credentials (v1 — reuses the existing customer columns, no schema change):
  pat_token = "email:api-token"   (Jira basic auth needs both, packed)
  org_url   = the site, e.g. "yoursite.atlassian.net" (with or without https)
  devops_project = the project KEY (falls back to the first project found)

Field mapping notes:
  - `type` is normalised by issue-type hierarchy level (1 → Epic, 0 → Story,
    -1 → Sub-task) so Bugs/Tasks appear at Story level instead of vanishing.
  - `board_column` is the status name and `board_column_done` comes from the
    status category — Jira boards group statuses into columns, and
    status-as-column is the faithful v1 without the Agile board-config API.
  - `id` is Jira's internal numeric issue id (satisfies the integer git_id
    contract); the human key (ABC-123) appears in titles/URLs.
"""

import re

import pandas as pd
import requests

from .base import TrackerCapabilities, TrackerProvider, WORK_ITEM_COLUMNS
from .registry import register_provider

# Jira priorities are named; the app renders 1-4 (and back for writes).
_PRIORITY_MAP = {"highest": 1, "high": 2, "medium": 3, "low": 4, "lowest": 4}
_PRIORITY_NAMES = {1: "Highest", 2: "High", 3: "Medium", 4: "Low"}

_SEARCH_FIELDS = (
    "summary,status,issuetype,parent,assignee,updated,priority,description"
)


def _adf_text(node, limit: int = 2000) -> str:
    """Plain text from an ADF (Atlassian Document Format) tree — recursively
    collects text nodes; block nodes contribute line breaks. Lossy by design:
    this feeds the search cache and lightweight previews."""
    parts: list = []

    def _walk(n):
        if isinstance(n, list):
            for item in n:
                _walk(item)
            return
        if not isinstance(n, dict):
            return
        if n.get("type") == "text":
            parts.append(n.get("text") or "")
        _walk(n.get("content") or [])
        if n.get("type") in ("paragraph", "heading", "listItem", "codeBlock",
                             "blockquote", "rule"):
            parts.append("\n")

    _walk(node)
    text = re.sub(r"[ \t]+", " ", "".join(parts))
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:limit]


def _normalise_site(raw: str) -> str:
    """'yoursite.atlassian.net' (any spelling) → 'https://yoursite.atlassian.net'."""
    site = str(raw or "").strip().rstrip("/")
    if site and not site.startswith("http"):
        site = f"https://{site}"
    return site


def _type_from_issuetype(issuetype: dict) -> str:
    """Normalise a Jira issue type to one of the hierarchy levels."""
    level = (issuetype or {}).get("hierarchyLevel")
    if level is not None:
        if level >= 1:
            return "Epic"
        if level <= -1:
            return "Sub-task"
        return "Story"
    if (issuetype or {}).get("subtask") is True:
        return "Sub-task"
    name = str((issuetype or {}).get("name") or "").lower()
    if name == "epic":
        return "Epic"
    if "sub" in name:
        return "Sub-task"
    return "Story"


def _text_to_adf(text) -> dict:
    """Plain/markdown-ish text → a minimal ADF doc (paragraphs, line breaks).

    Deliberately lossy: Jira Cloud's v3 API only accepts ADF and a full
    markdown→ADF converter is its own project — text (markdown syntax
    included) survives verbatim; blank lines split paragraphs."""
    content = []
    for para in re.split(r"\n\s*\n", str(text or "")):
        nodes: list = []
        for line in para.split("\n"):
            if nodes:
                nodes.append({"type": "hardBreak"})
            if line:
                nodes.append({"type": "text", "text": line})
        if nodes:
            content.append({"type": "paragraph", "content": nodes})
    if not content:
        content = [{"type": "paragraph", "content": []}]
    return {"type": "doc", "version": 1, "content": content}


def _http_error_detail(e: requests.HTTPError) -> str:
    """Jira packs useful validation errors into the response body — surface
    them instead of the bare '400 Client Error' string."""
    try:
        data = e.response.json()
        msgs = list(data.get("errorMessages") or [])
        msgs += [f"{k}: {v}" for k, v in (data.get("errors") or {}).items()]
        if msgs:
            return "; ".join(msgs)
    except Exception:
        pass
    return str(e)


@register_provider
class JiraProvider(TrackerProvider):
    """One customer's Jira Cloud connection (read-first v1)."""

    provider_key = "jira"
    display_name = "Jira"

    _TYPE_HIERARCHY = ("Epic", "Story", "Sub-task")

    def __init__(self, email: str, api_token: str, site: str, log,
                 project_key: str | None = None):
        self.email = email
        self.api_token = api_token
        self.site = _normalise_site(site)
        self.log = log
        self.configured_project = (project_key or "").strip() or None
        self.project_key: str | None = None
        self.available_projects: list = []
        self.customer_name = ""
        # Project issue types (for create) and status names (for the board
        # column / state dropdowns) — each fetched once, per provider.
        self._issue_types_cache: list | None = None
        self._statuses_cache: list | None = None

    # ── identity / classification ─────────────────────────────────────────
    @classmethod
    def type_hierarchy(cls) -> tuple:
        return cls._TYPE_HIERARCHY

    @classmethod
    def preferred_type(cls) -> str:
        # Sub-task is the leaf, but Story is the level people actually work at.
        return "Story"

    @classmethod
    def capabilities(cls) -> TrackerCapabilities:
        # Attachments are per-issue in Jira — the project-level upload the
        # image-paste flow expects doesn't exist, so v1 declares it off.
        return TrackerCapabilities(
            board_columns=True, hierarchy=True, comments=True, attachments=False
        )

    @classmethod
    def from_customer_row(cls, row, log):
        pat = str(row.get("pat_token") or "").strip()
        site = str(row.get("org_url") or "").strip()
        if not pat or not site or ":" not in pat:
            if pat and ":" not in pat:
                log.error(
                    f"Jira credentials for '{row.get('customer_name')}' must be "
                    "'email:api-token' in the PAT field — skipping"
                )
            return None
        email, token = pat.split(":", 1)
        provider = cls(
            email.strip(), token.strip(), site, log,
            project_key=row.get("devops_project"),
        )
        provider.customer_name = str(row.get("customer_name") or "")
        return provider

    # ── HTTP plumbing (kept small so tests can monkeypatch _request) ──────
    def _request(self, method: str, path: str, **kwargs):
        """One Jira REST call; returns parsed JSON or raises for HTTP errors."""
        resp = requests.request(
            method,
            f"{self.site}{path}",
            auth=(self.email, self.api_token),
            headers={"Accept": "application/json"},
            timeout=30,
            **kwargs,
        )
        resp.raise_for_status()
        return resp.json() if resp.text else {}

    # ── connection ────────────────────────────────────────────────────────
    def connect(self):
        try:
            projects = self._request(
                "GET", "/rest/api/3/project/search?maxResults=100"
            ).get("values", [])
            if not projects:
                raise Exception("No projects visible to this Jira account.")
            self.available_projects = [p["key"] for p in projects]
            if (
                self.configured_project
                and self.configured_project in self.available_projects
            ):
                self.project_key = self.configured_project
            else:
                if self.configured_project:
                    self.log.warning(
                        f"Configured Jira project '{self.configured_project}' not "
                        f"found on {self.site}; using '{self.available_projects[0]}'"
                    )
                self.project_key = self.available_projects[0]
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            if code in (401, 403):
                raise Exception(
                    "Jira authentication failed — check the email:api-token "
                    "value and that the token is still valid."
                )
            raise Exception(f"Failed to connect to Jira: {e}")

    # ── data ──────────────────────────────────────────────────────────────
    def _search_issues(self, jql: str) -> list:
        """All issues for a JQL query. Isolated for testability.

        Uses /search/jql with cursor pagination — the legacy offset-based
        /rest/api/3/search returns 410 Gone on current Jira Cloud sites."""
        issues, token = [], None
        while True:
            path = (
                "/rest/api/3/search/jql"
                f"?jql={requests.utils.quote(jql)}"
                f"&fields={_SEARCH_FIELDS}&maxResults=100"
            )
            if token:
                path += f"&nextPageToken={requests.utils.quote(str(token))}"
            page = self._request("GET", path)
            issues.extend(page.get("issues", []))
            token = page.get("nextPageToken")
            if not token:
                return issues

    def fetch_work_items(self, min_id=None, min_changed_date=None):
        """This customer's issues as the canonical work-item DataFrame.

        Incremental refresh uses the changed-date filter only — Jira ids don't
        grow per-project the way ADO's do, so `min_id` is ignored."""
        jql = f'project = "{self.project_key}"'
        if min_changed_date:
            stamp = str(min_changed_date)[:16].replace("T", " ")
            jql += f' AND updated >= "{stamp}"'
        jql += " ORDER BY updated DESC"

        # Degrade like the Azure provider: a failed fetch logs and yields an
        # empty frame — it must never abort the whole multi-customer preload.
        try:
            issues = self._search_issues(jql)
        except Exception as e:
            self.log.error(
                f"Jira issue fetch failed for {self.customer_name}: {e}"
            )
            return pd.DataFrame(columns=WORK_ITEM_COLUMNS)

        rows = []
        for issue in issues:
            f = issue.get("fields") or {}
            status = f.get("status") or {}
            parent = f.get("parent") or {}
            rows.append({
                "customer_name": self.customer_name,
                "type": _type_from_issuetype(f.get("issuetype")),
                "id": int(issue["id"]),
                "title": f"{issue.get('key', '')} {f.get('summary') or ''}".strip(),
                "state": str(status.get("name") or ""),
                "parent_id": int(parent["id"]) if parent.get("id") else None,
                "board_column": str(status.get("name") or ""),
                "board_column_done": int(
                    (status.get("statusCategory") or {}).get("key") == "done"
                ),
                "assigned_to": str(
                    (f.get("assignee") or {}).get("displayName") or ""
                ),
                "changed_date": str(f.get("updated") or ""),
                "priority": _PRIORITY_MAP.get(
                    str((f.get("priority") or {}).get("name") or "").lower()
                ),
                "description": _adf_text(f.get("description")),
            })
        if not rows:
            return pd.DataFrame(columns=WORK_ITEM_COLUMNS)
        return pd.DataFrame(rows, columns=WORK_ITEM_COLUMNS)

    def get_work_item_description(self, work_item_id):
        try:
            issue = self._request(
                "GET", f"/rest/api/3/issue/{int(work_item_id)}?fields="
                       "description,status,assignee,priority",
            )
            f = issue.get("fields") or {}
            live = {
                "state": str((f.get("status") or {}).get("name") or ""),
                "assigned_to": str(
                    (f.get("assignee") or {}).get("displayName") or ""
                ),
                "priority": _PRIORITY_MAP.get(
                    str((f.get("priority") or {}).get("name") or "").lower()
                ),
            }
            return (True, _adf_text(f.get("description"), limit=100_000),
                    "markdown", live)
        except Exception as e:
            self.log.error(f"Jira description fetch failed for {work_item_id}: {e}")
            return (False, f"Error fetching description: {e}", "markdown", {})

    def get_work_item_url(self, work_item_id):
        # The browse URL wants the human key; resolve it from the numeric id.
        try:
            issue = self._request(
                "GET", f"/rest/api/3/issue/{int(work_item_id)}?fields=summary"
            )
            return f"{self.site}/browse/{issue.get('key')}"
        except Exception:
            return None

    def get_board_columns_via_team_autodetect(self, board_type: str = None):
        """Board columns for this project — its statuses, mirroring the
        status-as-column mapping in fetch_work_items. (Azure-era method name;
        the handler layer calls it for the update dialog's column dropdown.)"""
        if self._statuses_cache:
            return (True, list(self._statuses_cache))
        try:
            data = self._request(
                "GET", f"/rest/api/3/project/{self.project_key}/statuses"
            )
            names, seen = [], set()
            for itype in data if isinstance(data, list) else []:
                for st in itype.get("statuses") or []:
                    nm = st.get("name")
                    if nm and nm.lower() not in seen:
                        seen.add(nm.lower())
                        names.append(nm)
            if names:
                self._statuses_cache = names
                return (True, list(names))
            return (False, "No statuses found for the project")
        except Exception as e:
            self.log.error(f"Jira status fetch failed for {self.project_key}: {e}")
            return (False, f"Error: {e}")

    def state_options(self) -> list:
        """Jira state == status == board column; the State dropdown should
        offer the project's statuses, not Azure's New/Active/... names."""
        ok, cols = self.get_board_columns_via_team_autodetect()
        return list(cols) if ok else super().state_options()

    # ── comments ──────────────────────────────────────────────────────────
    def get_work_item_comments(self, work_item_id):
        try:
            raw = self._request(
                "GET", f"/rest/api/3/issue/{int(work_item_id)}/comment"
            ).get("comments", [])
            comments = [
                {
                    "author": str((c.get("author") or {}).get("displayName") or ""),
                    "date": str(c.get("created") or ""),
                    "text": _adf_text(c.get("body")),
                }
                for c in raw
            ]
            comments.sort(key=lambda c: c["date"], reverse=True)
            return (True, comments)
        except Exception as e:
            self.log.error(f"Jira comments fetch failed for {work_item_id}: {e}")
            return (False, f"Error fetching comments: {e}")

    def add_comment_to_work_item(self, work_item_id, comment_text):
        try:
            self._request(
                "POST", f"/rest/api/3/issue/{int(work_item_id)}/comment",
                json={"body": _text_to_adf(comment_text)},
            )
            return (True, "Comment added")
        except Exception as e:
            self.log.error(f"Jira comment post failed for {work_item_id}: {e}")
            return (False, f"Error adding comment: {e}")

    # ── write plumbing ────────────────────────────────────────────────────
    def _issue_types(self) -> list:
        if self._issue_types_cache is None:
            data = self._request("GET", f"/rest/api/3/project/{self.project_key}")
            self._issue_types_cache = data.get("issueTypes") or []
        return self._issue_types_cache

    def _issue_type_for_level(self, type_key) -> dict:
        """The project's real issue type for one of our hierarchy levels —
        exact name match wins (Story over Task/Bug at the same level)."""
        wanted = str(type_key or "Story")
        candidates = [
            t for t in self._issue_types() if _type_from_issuetype(t) == wanted
        ]
        if not candidates:
            raise Exception(
                f"Project {self.project_key} has no issue type at the "
                f"'{wanted}' level"
            )
        exact = next(
            (t for t in candidates
             if str(t.get("name") or "").lower() == wanted.lower()),
            None,
        )
        return exact or candidates[0]

    def _resolve_account_id(self, name: str):
        """accountId of the assignable user best matching a name/email, or
        None — Jira Cloud only accepts accountIds, never display names."""
        try:
            users = self._request(
                "GET",
                "/rest/api/3/user/assignable/search"
                f"?project={requests.utils.quote(self.project_key or '')}"
                f"&query={requests.utils.quote(str(name))}",
            )
            if isinstance(users, list) and users:
                return users[0].get("accountId")
        except Exception as e:
            self.log.warning(f"Jira assignee lookup failed for '{name}': {e}")
        return None

    def _transition_to(self, issue_id: int, status_name: str) -> tuple:
        """Move an issue to the named status via a workflow transition."""
        target = str(status_name or "").strip()
        cur = self._request("GET", f"/rest/api/3/issue/{issue_id}?fields=status")
        cur_name = str(
            ((cur.get("fields") or {}).get("status") or {}).get("name") or ""
        )
        if cur_name.lower() == target.lower():
            return (True, f"Already in '{cur_name}'")
        transitions = self._request(
            "GET", f"/rest/api/3/issue/{issue_id}/transitions"
        ).get("transitions") or []
        match = next(
            (t for t in transitions
             if str((t.get("to") or {}).get("name") or "").lower()
             == target.lower()),
            None,
        )
        if not match:
            allowed = ", ".join(sorted(
                {str((t.get("to") or {}).get("name") or "") for t in transitions}
            ))
            return (False,
                    f"The workflow allows no move from '{cur_name}' to "
                    f"'{target}'" + (f" (allowed: {allowed})" if allowed else ""))
        self._request(
            "POST", f"/rest/api/3/issue/{issue_id}/transitions",
            json={"transition": {"id": match["id"]}},
        )
        return (True, f"Moved to '{target}'")

    def _translate_fields(self, azure_fields: dict) -> tuple:
        """(jira_fields, warnings) from the handler layer's Azure-era field
        names. System.State is NOT handled here — a status change is a
        workflow transition, not a field write."""
        out: dict = {}
        warnings: list = []
        src = azure_fields or {}
        desc = src.get("System.Description")
        if desc:
            out["description"] = _text_to_adf(desc)
        pr = src.get("Microsoft.VSTS.Common.Priority")
        if pr:
            try:
                name = _PRIORITY_NAMES.get(int(pr))
            except (TypeError, ValueError):
                name = None
            if name:
                out["priority"] = {"name": name}
        assignee = src.get("System.AssignedTo")
        if assignee:
            account_id = self._resolve_account_id(str(assignee))
            if account_id:
                out["assignee"] = {"accountId": account_id}
            else:
                warnings.append(f"no Jira user found for '{assignee}'")
        tags = src.get("System.Tags")
        if tags:
            labels = [  # Jira labels can't contain spaces
                t.strip().replace(" ", "-")
                for t in re.split(r"[;,]", str(tags)) if t.strip()
            ]
            if labels:
                out["labels"] = labels
        return out, warnings

    # ── writes ────────────────────────────────────────────────────────────
    def create_item(self, type_key, title, description=None,
                    additional_fields=None, markdown=False, parent=None):
        """Create an issue at the given hierarchy level. `markdown` is
        accepted for signature parity — text becomes minimal ADF either way.
        The success message keeps the Azure-era 'ID <n>' shape the handler
        layer regexes for the initial board-column move."""
        try:
            itype = self._issue_type_for_level(type_key)
            fields = {
                "project": {"key": self.project_key},
                "issuetype": {"id": str(itype["id"])},
                "summary": str(title or "").strip(),
            }
            if description:
                fields["description"] = _text_to_adf(description)
            if parent:
                fields["parent"] = {"id": str(int(parent))}
            extra, warnings = self._translate_fields(additional_fields)
            fields.update(extra)

            try:
                resp = self._request(
                    "POST", "/rest/api/3/issue", json={"fields": fields}
                )
            except requests.HTTPError as e:
                # Team-managed projects often keep optional fields (priority,
                # labels) off the create screen — retry once without exactly
                # the fields Jira itself rejected.
                resp = None
                if e.response is not None and e.response.status_code == 400:
                    bad = list((e.response.json().get("errors") or {}))
                    removable = [
                        b for b in bad
                        if b in fields
                        and b not in ("project", "issuetype", "summary", "parent")
                    ]
                    if removable:
                        for b in removable:
                            fields.pop(b)
                        warnings.append(
                            "not on the create screen, skipped: "
                            + ", ".join(removable)
                        )
                        resp = self._request(
                            "POST", "/rest/api/3/issue", json={"fields": fields}
                        )
                if resp is None:
                    raise

            new_id, key = resp.get("id"), resp.get("key")
            # A requested initial state is a post-create transition in Jira.
            state = (additional_fields or {}).get("System.State")
            if state:
                ok, msg = self._transition_to(int(new_id), str(state))
                if not ok:
                    warnings.append(msg)
            msg = f"Created {type_key} with ID {new_id} ({key})"
            if warnings:
                msg += " — " + "; ".join(warnings)
            self.log.info(msg)
            return (True, msg)
        except requests.HTTPError as e:
            detail = _http_error_detail(e)
            self.log.error(f"Jira create failed: {detail}")
            return (False, f"Jira create failed: {detail}")
        except Exception as e:
            self.log.error(f"Jira create failed: {e}")
            return (False, f"Jira create failed: {e}")

    # Named wrappers for the Azure-era manager surface. Feature maps to
    # Story — Jira's hierarchy has no middle Feature level.
    def create_user_story(self, title, description=None, additional_fields=None,
                          markdown=False, parent=None):
        return self.create_item(
            "Story", title, description, additional_fields, markdown, parent
        )

    def create_feature(self, title, description=None, additional_fields=None,
                       markdown=False, parent=None):
        return self.create_item(
            "Story", title, description, additional_fields, markdown, parent
        )

    def create_epic(self, title, description=None, additional_fields=None,
                    markdown=False):
        return self.create_item("Epic", title, description, additional_fields,
                                markdown)

    def get_workitem_level(self, *a, **kw):
        # Azure-era WIQL helper with no provider-neutral callers — the app
        # reads levels from the cached work-item frame instead.
        return (False, "Not supported for Jira")

    def update_work_item_fields(self, work_item_id, fields, markdown=False):
        """Update an issue from Azure-era field names. Field writes that
        succeed stay written even when a requested state transition is
        forbidden — that comes back as a warning in the message."""
        try:
            issue_id = int(work_item_id)
            payload, warnings = self._translate_fields(fields)
            if payload:
                self._request(
                    "PUT", f"/rest/api/3/issue/{issue_id}",
                    json={"fields": payload},
                )
            state = (fields or {}).get("System.State")
            if state:
                ok, msg = self._transition_to(issue_id, str(state))
                if not ok:
                    warnings.append(msg)
            if not payload and not state:
                return (True, f"No changes needed for work item {work_item_id}")
            msg = f"Updated work item {work_item_id}"
            if warnings:
                msg += " — " + "; ".join(warnings)
            self.log.info(msg)
            return (True, msg)
        except requests.HTTPError as e:
            detail = _http_error_detail(e)
            self.log.error(f"Jira update failed for {work_item_id}: {detail}")
            return (False, f"Jira update failed: {detail}")
        except Exception as e:
            self.log.error(f"Jira update failed for {work_item_id}: {e}")
            return (False, f"Jira update failed: {e}")

    def set_board_column(self, work_item_id, column_name):
        """Board moves are workflow transitions (column = status)."""
        try:
            return self._transition_to(int(work_item_id), column_name)
        except Exception as e:
            self.log.error(f"Jira transition failed for {work_item_id}: {e}")
            return (False, f"Error moving issue: {e}")

    # ── attachments: not supported in v1 ──────────────────────────────────
    def upload_attachment(self, file_name, content):
        return None

    def owns_attachment_url(self, url) -> bool:
        return False

    def fetch_attachment(self, url):
        return None
