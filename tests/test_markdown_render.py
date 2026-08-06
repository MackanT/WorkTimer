"""Tests for DevOps-attachment image proxying in the markdown renderer."""

from src.markdown_utils import render_and_sanitize_markdown

_ATTACH = "https://dev.azure.com/org/proj/_apis/wit/attachments/42?fileName=shot.png"


def test_devops_attachment_img_is_proxied_in_preview():
    html = render_and_sanitize_markdown(f"![shot]({_ATTACH})")
    # Rewritten to the authenticated proxy...
    assert "/devops_attachment?url=" in html
    # ...carrying the (url-encoded) original DevOps URL.
    assert "dev.azure.com" in html
    assert "%2F_apis%2Fwit%2Fattachments%2F42" in html


def test_local_and_other_images_are_left_alone():
    local = render_and_sanitize_markdown("![x](/notes_assets/note_assets/img.png)")
    assert "/devops_attachment" not in local
    assert "/notes_assets/" in local

    other = render_and_sanitize_markdown("![y](https://example.com/pic.png)")
    assert "/devops_attachment" not in other
