"""Work-item-linked branch creation (Azure Repos): name suggestion, the
vstfs artifact link, and the client's REST flow (mocked)."""

import src.tracker_manager as tm
from src.tracker_manager import AzureDevOpsClient, _branch_artifact_url
from src.trackers.base import suggest_branch_name


class _NullLog:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...


def test_suggest_branch_name_levels_and_slug():
    assert (
        suggest_branch_name("User Story", 123, "Fix the Läge thing!")
        == "story/123-fix-the-l-ge-thing"
    )
    assert suggest_branch_name("Feature", 7, "") == "feature/7"
    assert suggest_branch_name("", 9, "x") == "item/9-x"
    # Slug capped, no trailing dash.
    long = suggest_branch_name("Epic", 1, "a" * 60 + " b")
    assert long.startswith("epic/1-") and len(long) <= len("epic/1-") + 40


def test_suggest_branch_name_with_template():
    tpl = "feat/{{id}}-{{title}}"
    assert suggest_branch_name("User Story", 12, "Fix It", tpl) == "feat/12-fix-it"
    # {{type}} and spaced placeholders work; empty title strips cleanly.
    assert (
        suggest_branch_name("User Story", 12, "x", "{{ type }}s/{{ id }}-{{ title }}")
        == "storys/12-x"
    )
    assert suggest_branch_name("Epic", 3, "", "feat/{{id}}-{{title}}") == "feat/3"
    # A blank/garbage template falls back to the default shape.
    assert suggest_branch_name("Epic", 3, "x", "   ") == "epic/3-x"
    # A literal name (no placeholders) passes through untouched — the add
    # form's branch-name field may hold either a template or a fixed name.
    assert suggest_branch_name("Epic", 3, "x", "my/fixed-name") == "my/fixed-name"


def test_branch_template_flows_through_tracker_defaults():
    from src.tracker_defaults import DEFAULT_FIELDS, defaults_for

    assert "branch_template" in DEFAULT_FIELDS
    stored = {
        "rowico (devops)": {
            "*": {"branch_template": "feat/{{id}}-{{title}}"},
            "Epic": {"branch_template": "epic/{{id}}"},
        }
    }
    assert (
        defaults_for(stored, "rowico (devops)", "User Story")["branch_template"]
        == "feat/{{id}}-{{title}}"
    )
    assert (
        defaults_for(stored, "rowico (devops)", "Epic")["branch_template"]
        == "epic/{{id}}"
    )


def test_branch_artifact_url_encodes_everything():
    url = _branch_artifact_url("proj-guid", "repo-guid", "story/12-fix")
    assert url == "vstfs:///Git/Ref/proj-guid%2Frepo-guid%2FGBstory%2F12-fix"


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _WitStub:
    def __init__(self):
        self.calls = []

    def update_work_item(self, patch, work_item_id, project=None):
        self.calls.append((patch, work_item_id, project))


def _client():
    c = AzureDevOpsClient("pat", "https://dev.azure.com/org", _NullLog())
    c.project_name = "Proj"
    c.wit_client = _WitStub()
    return c


def test_create_branch_success_links_work_item(monkeypatch):
    posted = {}

    def fake_get(url, **kw):
        assert "refs?filter=heads/main" in url
        return _Resp(200, {"value": [
            {"name": "refs/heads/other", "objectId": "bad"},
            {"name": "refs/heads/main", "objectId": "abc123"},
        ]})

    def fake_post(url, json=None, **kw):
        posted["payload"] = json
        return _Resp(200, {"value": [{"success": True}]})

    monkeypatch.setattr(tm.requests, "get", fake_get)
    monkeypatch.setattr(tm.requests, "post", fake_post)

    c = _client()
    ok, msg = c.create_branch("repo1", "projid", "story/5-x", "main", 5)
    assert ok, msg
    assert posted["payload"] == [{
        "name": "refs/heads/story/5-x",
        "oldObjectId": "0" * 40,
        "newObjectId": "abc123",
    }]
    (patch, wid, project), = c.wit_client.calls
    assert wid == 5 and project == "Proj"
    assert patch[0]["value"]["rel"] == "ArtifactLink"
    assert patch[0]["value"]["url"] == _branch_artifact_url(
        "projid", "repo1", "story/5-x"
    )


def test_create_branch_source_missing(monkeypatch):
    monkeypatch.setattr(
        tm.requests, "get", lambda url, **kw: _Resp(200, {"value": []})
    )
    ok, msg = _client().create_branch("repo1", "projid", "b", "nope", 5)
    assert not ok and "not found" in msg


def test_create_branch_scope_error_maps_to_message(monkeypatch):
    monkeypatch.setattr(tm.requests, "get", lambda url, **kw: _Resp(203))
    ok, msg = _client().create_branch("repo1", "projid", "b", "main", 5)
    assert not ok and "Code scope" in msg
