"""Staged-image helpers: the add form's bridge for item-scoped attachment
stores (Jira) — bytes are held until the item exists, then uploaded."""

from src.ui.work_item_forms import (
    _STAGED_IMAGES,
    stage_image,
    strip_staged_image_lines,
    take_staged_images,
)


def test_stage_take_roundtrip_consumes_entries():
    url = stage_image("shot.png", b"png-bytes")
    assert url.startswith("/staged_image/")

    md = f"Before\n\n![shot.png]({url})\n\nAfter"
    staged = take_staged_images(md)
    assert staged == [(url, "shot.png", b"png-bytes")]
    # Consumed — a second take finds nothing.
    assert take_staged_images(md) == []


def test_strip_staged_image_lines_removes_only_staged_refs():
    url = stage_image("a.png", b"x")
    md = (
        "Intro\n"
        f"![a.png]({url})\n"
        "![real](https://x.atlassian.net/rest/api/3/attachment/content/1)\n"
        "Outro"
    )
    stripped = strip_staged_image_lines(md)
    assert url not in stripped
    assert "attachment/content/1" in stripped   # real refs untouched
    assert "Intro" in stripped and "Outro" in stripped
    take_staged_images(md)  # tidy the module store


def test_stage_prune_drops_old_entries():
    url = stage_image("old.png", b"x")
    token = url.rsplit("/", 1)[1]
    name, content, ts = _STAGED_IMAGES[token]
    _STAGED_IMAGES[token] = (name, content, ts - 7200)  # 2 h old
    stage_image("new.png", b"y")  # staging prunes stale entries
    assert token not in _STAGED_IMAGES
