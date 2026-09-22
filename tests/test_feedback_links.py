"""The prefilled GitHub new-issue links (Report a bug / Request a feature)."""

from urllib.parse import parse_qs, unquote, urlparse

from src.services.update_checker import github_issue_url


def test_bug_link_prefills_label_title_and_env():
    url = github_issue_url("bug")
    parsed = urlparse(url)
    assert parsed.netloc == "github.com"
    assert parsed.path == "/mackant/worktimer/issues/new"
    q = parse_qs(parsed.query)
    assert q["labels"] == ["bug"]
    assert q["title"][0].startswith("[Bug]")
    body = q["body"][0]
    assert "## What happened" in body and "WorkTimer v" in body


def test_feature_link_uses_enhancement_label():
    q = parse_qs(urlparse(github_issue_url("feature")).query)
    assert q["labels"] == ["enhancement"]
    assert q["title"][0].startswith("[Feature]")
    assert "## The idea" in q["body"][0]


def test_link_is_fully_url_encoded():
    url = github_issue_url("bug")
    # Nothing after the ? should carry raw spaces or newlines.
    query = url.split("?", 1)[1]
    assert " " not in query and "\n" not in query
    assert "\n" in unquote(query.replace("+", " "))
