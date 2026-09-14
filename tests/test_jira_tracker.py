"""Offline tests for the Jira tracker module (faked REST payloads)."""

import logging

import requests

from src.trackers.base import WORK_ITEM_COLUMNS
from src.trackers.jira import (
    JiraProvider, _adf_text, _normalise_site, _text_to_adf,
)
from src.trackers.registry import create_provider_for_row, get_provider_class

_log = logging.getLogger("test_jira")


def _row(**over):
    base = {
        "customer_name": "Jira Co",
        "pat_token": "me@example.com:secrettoken",
        "org_url": "myteam.atlassian.net",
        "devops_project": "ABC",
        "integration_type": "jira",
    }
    base.update(over)
    return base


def _adf(*paragraph_texts):
    return {
        "type": "doc", "version": 1,
        "content": [
            {"type": "paragraph",
             "content": [{"type": "text", "text": t}]}
            for t in paragraph_texts
        ],
    }


# ── registration / construction ─────────────────────────────────────────────

def test_jira_provider_is_registered():
    assert get_provider_class("jira") is JiraProvider


def test_from_customer_row_unpacks_email_token_and_site():
    p = create_provider_for_row(_row(), _log)
    assert isinstance(p, JiraProvider)
    assert p.email == "me@example.com"
    assert p.api_token == "secrettoken"
    assert p.site == "https://myteam.atlassian.net"
    assert p.configured_project == "ABC"
    assert p.customer_name == "Jira Co"
    assert p.type_hierarchy() == ("Epic", "Story", "Sub-task")
    # Attachments are per-issue: supported, but only where an item exists.
    assert p.capabilities().attachments is True
    assert p.capabilities().attachments_require_item is True


def test_from_customer_row_rejects_unpacked_credentials():
    assert create_provider_for_row(_row(pat_token="token-without-email"), _log) is None
    assert create_provider_for_row(_row(pat_token=""), _log) is None


def test_site_normalisation():
    assert _normalise_site("x.atlassian.net/") == "https://x.atlassian.net"
    assert _normalise_site("https://x.atlassian.net") == "https://x.atlassian.net"


# ── ADF text extraction ─────────────────────────────────────────────────────

def test_adf_text_extracts_nested_content():
    doc = {
        "type": "doc", "version": 1,
        "content": [
            {"type": "heading", "attrs": {"level": 1},
             "content": [{"type": "text", "text": "Title"}]},
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Hello "},
                {"type": "text", "text": "world", "marks": [{"type": "strong"}]},
            ]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph",
                     "content": [{"type": "text", "text": "item one"}]},
                ]},
            ]},
        ],
    }
    text = _adf_text(doc)
    # ADF → markdown-ish: structure and marks survive as markdown.
    assert text == "# Title\n\nHello **world**\n\n- item one"
    assert _adf_text(None) == ""


# ── payload normalisation ───────────────────────────────────────────────────

def _fake_issues():
    return [
        {  # Epic (hierarchy level 1)
            "id": "10001", "key": "ABC-1",
            "fields": {
                "summary": "Big epic",
                "issuetype": {"name": "Epic", "hierarchyLevel": 1},
                "status": {"name": "In Progress",
                           "statusCategory": {"key": "indeterminate"}},
                "assignee": {"displayName": "Alice"},
                "updated": "2026-09-01T10:00:00.000+0000",
                "priority": {"name": "High"},
                "description": _adf("The epic description"),
            },
        },
        {  # Bug at standard level → normalised to Story
            "id": "10002", "key": "ABC-2",
            "fields": {
                "summary": "Broken login",
                "issuetype": {"name": "Bug", "hierarchyLevel": 0},
                "status": {"name": "Done", "statusCategory": {"key": "done"}},
                "parent": {"id": "10001", "key": "ABC-1"},
                "assignee": None,
                "updated": "2026-09-02T09:00:00.000+0000",
                "priority": {"name": "Lowest"},
                "description": None,
            },
        },
    ]


def _connected_provider(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    p.project_key = "ABC"
    monkeypatch.setattr(p, "_search_issues", lambda jql: _fake_issues())
    return p


def test_fetch_work_items_normalises_to_canonical_schema(monkeypatch):
    p = _connected_provider(monkeypatch)
    df = p.fetch_work_items()
    assert list(df.columns) == WORK_ITEM_COLUMNS
    assert len(df) == 2

    epic = df[df["id"] == 10001].iloc[0]
    assert epic["type"] == "Epic"
    assert epic["title"] == "ABC-1 Big epic"          # key kept visible
    assert epic["board_column"] == "In Progress"
    assert epic["board_column_done"] == 0
    assert epic["assigned_to"] == "Alice"
    assert epic["priority"] == 2                       # High → 2
    assert epic["description"] == "The epic description"

    bug = df[df["id"] == 10002].iloc[0]
    assert bug["type"] == "Story"                      # Bug → Story level
    assert bug["parent_id"] == 10001
    assert bug["board_column_done"] == 1               # statusCategory done
    assert bug["priority"] == 4                        # Lowest → 4
    assert bug["assigned_to"] == ""


def test_fetch_work_items_incremental_uses_changed_date(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    p.project_key = "ABC"
    seen = {}
    monkeypatch.setattr(
        p, "_search_issues", lambda jql: seen.setdefault("jql", jql) and []
    )
    p.fetch_work_items(min_id=999, min_changed_date="2026-09-01T10:00")
    assert 'updated >= "2026-09-01 10:00"' in seen["jql"]
    assert "999" not in seen["jql"]  # min_id deliberately ignored


def test_search_issues_follows_next_page_token(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    pages = {
        None: {"issues": [{"id": "1"}], "nextPageToken": "tok2"},
        "tok2": {"issues": [{"id": "2"}]},  # no token → last page
    }
    calls = []

    def _fake_request(method, path, **kw):
        calls.append(path)
        token = None
        if "nextPageToken=" in path:
            token = path.split("nextPageToken=")[1].split("&")[0]
        return pages[token]

    monkeypatch.setattr(p, "_request", _fake_request)
    issues = p._search_issues("project = X")
    assert [i["id"] for i in issues] == ["1", "2"]
    assert all("/rest/api/3/search/jql" in c for c in calls)  # not the 410'd legacy path
    assert len(calls) == 2


def test_fetch_work_items_degrades_to_empty_on_error(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    p.project_key = "ABC"

    def _boom(jql):
        raise RuntimeError("410 Gone")

    monkeypatch.setattr(p, "_search_issues", _boom)
    df = p.fetch_work_items()
    assert df.empty and list(df.columns) == WORK_ITEM_COLUMNS


def test_preferred_type_is_story_not_the_subtask_leaf():
    # Jira's leaf (Sub-task) is auxiliary — boards should default to Story.
    assert JiraProvider.preferred_type() == "Story"
    # Azure inherits the base default: the hierarchy leaf itself. Imported
    # here (not at module top) — registration is an import side effect and
    # this file otherwise runs without the Azure module.
    from src.trackers import azure  # noqa: F401

    azure_cls = get_provider_class("devops")
    assert azure_cls.preferred_type() == azure_cls.type_hierarchy()[-1] == "User Story"


def test_board_columns_come_from_project_statuses(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    p.project_key = "ABC"
    payload = [  # /project/{key}/statuses: one entry per issue type —
        # Jira lists them in arbitrary order (Done first here); the result
        # must follow the workflow: new → indeterminate → done.
        {"name": "Story", "statuses": [
            {"name": "Done", "statusCategory": {"key": "done"}},
            {"name": "In Progress",
             "statusCategory": {"key": "indeterminate"}},
            {"name": "To Do", "statusCategory": {"key": "new"}},
        ]},
        {"name": "Sub-task", "statuses": [
            {"name": "To Do", "statusCategory": {"key": "new"}},  # dupe
            {"name": "Done", "statusCategory": {"key": "done"}},
        ]},
    ]
    monkeypatch.setattr(p, "_request", lambda m, path, **kw: payload)
    status, columns = p.get_board_columns_via_team_autodetect()
    assert status is True
    assert columns == ["To Do", "In Progress", "Done"]


def test_capabilities_mark_state_as_the_board_column():
    caps = JiraProvider.capabilities()
    assert caps.distinct_board_column is False  # status IS the column
    azure_cls = get_provider_class("devops")
    if azure_cls is not None:
        assert azure_cls.capabilities().distinct_board_column is True


def test_board_columns_degrade_gracefully(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    p.project_key = "ABC"

    def _boom(method, path, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(p, "_request", _boom)
    status, msg = p.get_board_columns_via_team_autodetect()
    assert status is False and "boom" in msg

    monkeypatch.setattr(p, "_request", lambda m, path, **kw: [])
    status, msg = p.get_board_columns_via_team_autodetect()
    assert status is False


# ── writes (v2) ─────────────────────────────────────────────────────────────

_ISSUE_TYPES = [
    {"id": "1", "name": "Epic", "hierarchyLevel": 1},
    {"id": "2", "name": "Task", "hierarchyLevel": 0},
    {"id": "3", "name": "Story", "hierarchyLevel": 0},
    {"id": "4", "name": "Subtask", "hierarchyLevel": -1, "subtask": True},
]


def test_text_to_adf_paragraphs_and_linebreaks():
    doc = _text_to_adf("line one\nline two\n\nsecond para")
    assert doc["type"] == "doc" and doc["version"] == 1
    p1, p2 = doc["content"]
    assert [n["type"] for n in p1["content"]] == ["text", "hardBreak", "text"]
    assert p2["content"][0]["text"] == "second para"
    assert _text_to_adf("")["content"]  # empty text still a valid doc


def test_text_to_adf_markdown_blocks():
    md = (
        "## Status\n"
        "\n"
        "Work is **done** with `code` and a [link](https://x.se).\n"
        "\n"
        "- first\n"
        "- second\n"
        "\n"
        "1. one\n"
        "2. two\n"
        "\n"
        "> a quote\n"
        "\n"
        "```python\n"
        "x = 1\n"
        "```\n"
        "\n"
        "---\n"
    )
    kinds = [b["type"] for b in _text_to_adf(md)["content"]]
    assert kinds == [
        "heading", "paragraph", "bulletList", "orderedList",
        "blockquote", "codeBlock", "rule",
    ]
    doc = _text_to_adf(md)["content"]
    assert doc[0]["attrs"] == {"level": 2}
    para = doc[1]["content"]
    assert {"type": "strong"} in (para[1].get("marks") or [])
    assert {"type": "code"} in (para[3].get("marks") or [])
    assert para[5]["marks"][0] == {
        "type": "link", "attrs": {"href": "https://x.se"}
    }
    assert len(doc[2]["content"]) == 2                  # two bullets
    assert doc[5]["attrs"] == {"language": "python"}
    assert doc[5]["content"][0]["text"] == "x = 1"


def test_text_to_adf_image_line_becomes_external_media():
    url = "https://x.atlassian.net/rest/api/3/attachment/content/10001"
    doc = _text_to_adf(f"before\n\n![shot.png]({url})\n\nafter")
    kinds = [b["type"] for b in doc["content"]]
    assert kinds == ["paragraph", "mediaSingle", "paragraph"]
    media = doc["content"][1]["content"][0]
    assert media == {
        "type": "media", "attrs": {"type": "external", "url": url}
    }


def test_text_to_adf_tables_and_task_lists():
    md = (
        "| Col 1 | Col 2 |\n"
        "| ---: | :-- |\n"
        "| A | B |\n"
        "| C | D |\n"
        "\n"
        "- [ ] open task\n"
        "- [x] done task\n"
    )
    doc = _text_to_adf(md)["content"]
    assert [b["type"] for b in doc] == ["table", "taskList"]

    table = doc[0]
    row_kinds = [
        row["content"][0]["type"] for row in table["content"]
    ]
    assert row_kinds == ["tableHeader", "tableCell", "tableCell"]
    assert len(table["content"]) == 3  # header + 2 body rows (sep consumed)
    first_cell = table["content"][0]["content"][0]
    assert first_cell["content"][0]["content"][0]["text"] == "Col 1"

    tasklist = doc[1]
    states = [i["attrs"]["state"] for i in tasklist["content"]]
    assert states == ["TODO", "DONE"]
    assert all(i["attrs"].get("localId") for i in tasklist["content"])
    assert tasklist["content"][0]["content"][0]["text"] == "open task"

    # Read side mirrors both (alignment colons normalise to ---).
    back = _adf_text(_text_to_adf(md), limit=10_000)
    assert "| Col 1 | Col 2 |" in back
    assert "| --- | --- |" in back
    assert "| A | B |" in back
    assert "- [ ] open task" in back and "- [x] done task" in back


def test_adf_markdown_round_trip():
    md = (
        "# Title\n"
        "\n"
        "Some **bold** and *italic* text.\n"
        "\n"
        "- item one\n"
        "- item two\n"
        "\n"
        "```sql\n"
        "select 1\n"
        "```"
    )
    assert _adf_text(_text_to_adf(md), limit=10_000) == md


def test_upload_attachment_targets_the_issue(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    seen = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{
                "id": "9001",
                "content": "https://myteam.atlassian.net/rest/api/3/"
                           "attachment/content/9001",
            }]

    def _fake_post(url, **kw):
        seen["url"] = url
        seen["headers"] = kw.get("headers") or {}
        return _Resp()

    monkeypatch.setattr("src.trackers.jira.requests.post", _fake_post)

    # No work item → per-issue store has nowhere to put it.
    assert p.upload_attachment("a.png", b"x") is None

    url = p.upload_attachment("a.png", b"x", work_item_id=10001)
    assert url.endswith("/attachment/content/9001")
    assert "/issue/10001/attachments" in seen["url"]
    assert seen["headers"].get("X-Atlassian-Token") == "no-check"

    # The returned content URL is owned (proxied) by this provider.
    assert p.owns_attachment_url(url) is True
    assert p.owns_attachment_url("https://evil.example/x") is False


def test_create_item_resolves_issue_type_parent_and_priority(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    p.project_key = "ABC"
    p._issue_types_cache = _ISSUE_TYPES
    posted = {}

    def _fake(method, path, **kw):
        assert method == "POST" and path == "/rest/api/3/issue"
        posted.update(kw["json"])
        return {"id": "10050", "key": "ABC-50"}

    monkeypatch.setattr(p, "_request", _fake)
    ok, msg = p.create_item(
        "Story", "New thing", description="Body",
        additional_fields={
            "Microsoft.VSTS.Common.Priority": 2,
            "System.Tags": "api; needs review",
        },
        parent=10001,
    )
    assert ok is True and "ID 10050" in msg and "ABC-50" in msg
    fields = posted["fields"]
    assert fields["issuetype"] == {"id": "3"}       # exact 'Story' beats Task
    assert fields["summary"] == "New thing"
    assert fields["parent"] == {"id": "10001"}
    assert fields["priority"] == {"name": "High"}
    assert fields["labels"] == ["api", "needs-review"]  # spaces → dashes
    assert fields["description"]["type"] == "doc"


def test_create_item_retries_without_rejected_fields(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    p.project_key = "ABC"
    p._issue_types_cache = _ISSUE_TYPES

    class _Resp:
        status_code = 400
        text = "field not on screen"

        def json(self):
            return {"errors": {"priority": "cannot be set"}}

    attempts = []

    def _fake(method, path, **kw):
        # Deep-copy: the provider strips rejected fields from the same dict
        # before retrying, so a reference would show the mutated payload.
        import copy

        attempts.append(copy.deepcopy(kw["json"]))
        if len(attempts) == 1:
            raise requests.HTTPError(response=_Resp())
        return {"id": "10051", "key": "ABC-51"}

    monkeypatch.setattr(p, "_request", _fake)
    ok, msg = p.create_item(
        "Epic", "t", additional_fields={"Microsoft.VSTS.Common.Priority": 1}
    )
    assert ok is True and "ID 10051" in msg and "skipped" in msg
    assert "priority" in attempts[0]["fields"]
    assert "priority" not in attempts[1]["fields"]
    assert attempts[1]["fields"]["issuetype"] == {"id": "1"}  # Epic level


def test_set_board_column_is_a_workflow_transition(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    posted = {}

    def _fake(method, path, **kw):
        if path.endswith("?fields=status"):
            return {"fields": {"status": {"name": "To Do"}}}
        if method == "GET" and path.endswith("/transitions"):
            return {"transitions": [
                {"id": "21", "to": {"name": "In Progress"}},
                {"id": "31", "to": {"name": "Done"}},
            ]}
        if method == "POST" and path.endswith("/transitions"):
            posted.update(kw["json"])
            return {}
        return {}

    monkeypatch.setattr(p, "_request", _fake)
    ok, _ = p.set_board_column(10001, "Done")
    assert ok is True and posted == {"transition": {"id": "31"}}

    ok, msg = p.set_board_column(10001, "To Do")     # already there → no-op
    assert ok is True and "Already" in msg

    ok, msg = p.set_board_column(10001, "Blocked")   # workflow forbids
    assert ok is False and "Blocked" in msg and "In Progress" in msg


def test_update_fields_translates_and_transitions(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    p.project_key = "ABC"
    put_fields = {}
    transitioned = []

    def _fake(method, path, **kw):
        if method == "PUT":
            put_fields.update(kw["json"]["fields"])
            return {}
        if path.startswith("/rest/api/3/user/assignable/search"):
            return [{"accountId": "abc123", "displayName": "Alice"}]
        if path.endswith("?fields=status"):
            return {"fields": {"status": {"name": "To Do"}}}
        if method == "GET" and path.endswith("/transitions"):
            return {"transitions": [{"id": "31", "to": {"name": "Done"}}]}
        if method == "POST" and path.endswith("/transitions"):
            transitioned.append(kw["json"]["transition"]["id"])
            return {}
        return {}

    monkeypatch.setattr(p, "_request", _fake)
    ok, _ = p.update_work_item_fields(10001, {
        "System.Description": "New body",
        "Microsoft.VSTS.Common.Priority": 3,
        "System.AssignedTo": "Alice",
        "System.State": "Done",
    })
    assert ok is True
    assert put_fields["priority"] == {"name": "Medium"}
    assert put_fields["assignee"] == {"accountId": "abc123"}
    assert put_fields["description"]["type"] == "doc"
    assert transitioned == ["31"]


def test_update_fields_unknown_state_warns_but_succeeds(monkeypatch):
    p = create_provider_for_row(_row(), _log)
    p.project_key = "ABC"

    def _fake(method, path, **kw):
        if method == "PUT":
            return {}
        if path.endswith("?fields=status"):
            return {"fields": {"status": {"name": "To Do"}}}
        if method == "GET" and path.endswith("/transitions"):
            return {"transitions": [{"id": "31", "to": {"name": "Done"}}]}
        return {}

    monkeypatch.setattr(p, "_request", _fake)
    # Azure-era state name that no Jira workflow knows → warning, not failure.
    ok, msg = p.update_work_item_fields(
        10001, {"System.Description": "x", "System.State": "Active"}
    )
    assert ok is True and "Active" in msg


def test_attachments_remain_stubbed():
    p = create_provider_for_row(_row(), _log)
    assert p.upload_attachment("a.png", b"x") is None
    assert p.owns_attachment_url("https://x.atlassian.net/whatever") is False
    assert p.fetch_attachment("u") is None
