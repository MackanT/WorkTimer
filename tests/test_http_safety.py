"""The security review's fixes (v6 Phase 6): what files reach the browser as,
the cross-site guard, tracker URL checks, Jira Cloud only, the stored-token
rule in Test connection, and the caps on what users can make the server hold."""

import gzip
import logging
import os
import sys

import pytest
from starlette.requests import Request

from src import importer, pat_crypto
from src.http_safety import FILE_HEADERS, file_response, image_type, is_cross_site
from src.pages.add_data import _same_place
from src.trackers.azure import AzureDevOpsProvider
from src.trackers.base import TrackerProvider
from src.trackers.jira import JiraProvider
from src.ui import work_item_forms

LOG = logging.getLogger("tests.http_safety")


# ── files served back to the browser ────────────────────────────────────────


@pytest.mark.parametrize("filename, ctype, expected", [
    ("shot.png", None, "image/png"),
    ("x", "image/jpeg; charset=binary", "image/jpeg"),
    ("evil.svg", None, None),
    ("x", "image/svg+xml", None),
    ("page.html", None, None),
    ("looks.png", "text/html", None),  # the reported type wins
])
def test_only_raster_images_are_images(filename, ctype, expected):
    assert image_type(filename, ctype) == expected


def test_anything_else_downloads_and_every_file_is_sandboxed():
    image = file_response(b"png", filename="a.png")
    other = file_response(b"<svg onload=alert(1)/>", content_type="image/svg+xml")

    assert image.media_type == "image/png" and "content-disposition" not in image.headers
    assert other.media_type == "application/octet-stream"
    assert other.headers["content-disposition"] == "attachment"
    for response in (image, other):
        for name, value in FILE_HEADERS.items():
            assert response.headers[name] == value


# ── the cross-site guard ────────────────────────────────────────────────────


def _request(method="POST", **headers):
    return Request({"type": "http", "method": method, "path": "/upload_image",
                    "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]})


@pytest.mark.parametrize("method, headers, refused", [
    ("POST", {"sec_fetch_site": "cross-site"}, True),
    ("POST", {"sec_fetch_site": "same-site"}, True),  # another subdomain is another site
    ("POST", {"sec_fetch_site": "same-origin"}, False),
    ("POST", {"sec_fetch_site": "none"}, False),
    ("POST", {"origin": "https://evil.example", "host": "worktimer.example.net"}, True),
    ("POST", {"origin": "https://worktimer.example.net", "host": "worktimer.example.net"}, False),
    ("POST", {}, False),  # no browser marker at all
    ("GET", {"sec_fetch_site": "cross-site"}, False),  # a link or an image
])
def test_state_changing_requests_from_other_sites_are_refused(method, headers, refused):
    assert is_cross_site(_request(method, **headers)) is refused


# ── tracker URLs: exactly the tracker's own attachments ────────────────────


@pytest.mark.parametrize("url, owned", [
    ("https://acme.atlassian.net/rest/api/3/attachment/content/1", True),
    ("https://acme.atlassian.net/rest/api/3/attachment/../../myself", False),
    ("https://acme.atlassian.net/rest/api/3/attachment/%2e%2e/%2e%2e/myself", False),
    ("https://evil.example/rest/api/3/attachment/content/1", False),
    ("https://acme.atlassian.net.evil.example/rest/api/3/attachment/content/1", False),
    ("https://me:pw@acme.atlassian.net/rest/api/3/attachment/content/1", False),
    ("http://acme.atlassian.net/rest/api/3/attachment/content/1", False),
])
def test_jira_owns_only_its_own_attachment_urls(url, owned):
    assert JiraProvider("a@b.c", "t", "acme.atlassian.net", LOG).owns_attachment_url(url) is owned


def test_azure_owns_only_its_own_orgs_attachments():
    ado = AzureDevOpsProvider.__new__(AzureDevOpsProvider)  # no connection needed
    ado.organization_url = "https://dev.azure.com/rowico"

    assert ado.owns_attachment_url("https://dev.azure.com/rowico/proj/_apis/wit/attachments/1")
    assert not ado.owns_attachment_url("https://dev.azure.com/rowicoEVIL/p/_apis/wit/attachments/1")
    assert not ado.owns_attachment_url("https://dev.azure.com/rowico/p/_apis/wit/items/1")
    assert not TrackerProvider.owned_url("https://x.example/a", "no-scheme")


def test_jira_talks_to_jira_cloud_only():
    other = JiraProvider("a@b.c", "t", "https://jira.internal.example", LOG)

    with pytest.raises(Exception, match="not a Jira Cloud site"):
        other.connect()
    assert not other.owns_attachment_url("https://jira.internal.example/rest/api/3/attachment/1")


class _Resp:
    def __init__(self, url, location=None, content=b"", ctype="image/png"):
        self.url, self.content = url, content
        self.is_redirect = location is not None
        self.headers = {"Location": location, "Content-Type": ctype} if location else {"Content-Type": ctype}

    def raise_for_status(self):
        pass


@pytest.mark.parametrize("target, fetched", [
    ("https://api.media.atlassian.com/file/abc/binary?token=x", True),
    ("http://169.254.169.254/latest/meta-data/", False),
    ("https://evil.example/steal", False),
    ("http://api.media.atlassian.com/file/abc", False),  # not https
])
def test_jira_attachment_redirects_stay_with_atlassian(monkeypatch, target, fetched):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs.get("auth")))
        if len(calls) == 1:
            return _Resp(url, location=target)
        return _Resp(url, content=b"png")

    monkeypatch.setattr("src.trackers.jira.requests.get", fake_get)
    jira = JiraProvider("a@b.c", "secret", "acme.atlassian.net", LOG)

    result = jira.fetch_attachment("https://acme.atlassian.net/rest/api/3/attachment/content/1")

    assert (result is not None) is fetched
    if fetched:
        assert calls[1] == (target, None)  # the credentials stay behind


def test_a_stored_secret_only_goes_back_where_it_came_from():
    assert _same_place("rowico", "https://rowico/")
    assert _same_place("https://Acme.atlassian.net", "acme.atlassian.net")
    assert not _same_place("https://evil.example", "acme.atlassian.net")


# ── caps on what users can make the server hold ─────────────────────────────


def test_staged_images_are_images_capped_per_user(monkeypatch):
    monkeypatch.setattr(work_item_forms, "_STAGED_IMAGES", {})
    with pytest.raises(ValueError, match="Only images"):
        work_item_forms.stage_image("page.html", b"<html>", 1)
    with pytest.raises(ValueError, match="too large"):
        work_item_forms.stage_image("big.png", b"x" * (work_item_forms.STAGED_MAX_BYTES + 1), 1)
    for _ in range(work_item_forms.STAGED_MAX_PER_USER):
        work_item_forms.stage_image("a.png", b"png", 1)
    with pytest.raises(ValueError, match="Too many"):
        work_item_forms.stage_image("a.png", b"png", 1)
    work_item_forms.stage_image("a.png", b"png", 2)  # another user's own allowance


def test_an_export_that_unpacks_too_far_is_refused(tmp_path, monkeypatch):
    bomb = tmp_path / "export.json.gz"
    with gzip.open(bomb, "wb") as f:
        f.write(b"0" * 5000)
    monkeypatch.setattr(importer, "MAX_EXPORT_BYTES", 1000)

    with pytest.raises(ValueError, match="unpacks to more than"):
        importer.prepare(str(bomb), db=None)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_the_token_key_is_readable_by_its_owner_only(tmp_path):
    pat_crypto.encrypt_pat("a-token", str(tmp_path / "worktimer.db"), LOG)

    assert os.stat(tmp_path / ".pat_key").st_mode & 0o777 == 0o600
