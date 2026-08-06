"""Tests for multi-project selection helpers in src/devops.py."""

import logging

import pandas as pd

from src.devops import DevOpsClient, DevOpsManager, _choose_project, _clean_project


def test_clean_project_normalises_blanks_and_sentinels():
    assert _clean_project(None) is None
    assert _clean_project("") is None
    assert _clean_project("   ") is None
    assert _clean_project("none") is None
    assert _clean_project("NULL") is None
    assert _clean_project("nan") is None
    assert _clean_project(float("nan")) is None
    assert _clean_project(pd.NA) is None


def test_clean_project_keeps_real_names_trimmed():
    assert _clean_project("MyProject") == "MyProject"
    assert _clean_project("  Spaces  ") == "Spaces"


AVAILABLE = ["Alpha", "Beta", "Gamma"]


def test_choose_configured_when_present():
    assert _choose_project("Beta", AVAILABLE) == "Beta"


def test_choose_falls_back_to_first_when_configured_missing():
    # Configured project no longer exists in the org -> first (today's default).
    assert _choose_project("Zeta", AVAILABLE) == "Alpha"


def test_choose_defaults_to_first_when_unconfigured():
    assert _choose_project(None, AVAILABLE) == "Alpha"
    assert _choose_project("", AVAILABLE) == "Alpha"


def test_choose_none_when_no_projects():
    assert _choose_project("Beta", []) is None
    assert _choose_project(None, []) is None


class _FakeWit:
    def __init__(self):
        self.captured = {}

    def create_attachment(self, upload_stream, project=None, file_name=None):
        # create_attachment streams via .read(), so this MUST be file-like.
        self.captured["read_bytes"] = upload_stream.read()
        self.captured["project"] = project
        self.captured["file_name"] = file_name
        return type("Ref", (), {"url": "https://dev.azure.com/o/_apis/wit/attachments/42"})()


def _client_with(wit):
    c = DevOpsClient.__new__(DevOpsClient)  # bypass network __init__
    c.wit_client = wit
    c.project_name = "MyProject"
    c.log = logging.getLogger("test")
    return c


def test_upload_attachment_wraps_bytes_in_readable_stream():
    wit = _FakeWit()
    url = _client_with(wit).upload_attachment("shot.png", b"PNGDATA")
    # Regression: raw bytes have no .read(); must be wrapped (BytesIO).
    assert wit.captured["read_bytes"] == b"PNGDATA"
    assert wit.captured["file_name"] == "shot.png"
    assert wit.captured["project"] == "MyProject"
    assert url.endswith("/attachments/42")


def test_upload_attachment_returns_none_on_error():
    class _Boom:
        def create_attachment(self, **kwargs):
            raise RuntimeError("boom")

    assert _client_with(_Boom()).upload_attachment("x.png", b"x") is None


def test_fetch_attachment_ssrf_guard():
    m = DevOpsManager.__new__(DevOpsManager)  # bypass network __init__
    m.clients = {}
    m.log = logging.getLogger("test")
    # Not a work-item attachment URL -> rejected outright (no request attempted).
    assert m.fetch_attachment("https://evil.example/steal") is None
    # Right shape but no connected client owns that org -> None (no request).
    assert m.fetch_attachment(
        "https://dev.azure.com/o/p/_apis/wit/attachments/1"
    ) is None
