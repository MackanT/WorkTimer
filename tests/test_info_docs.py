"""The Documentation page's tabs name files that exist under docs/ — with the
exact case: the container's filesystem is case-sensitive, Windows' isn't."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_every_documentation_tab_names_an_existing_file():
    info_page = yaml.safe_load((ROOT / "config" / "config_ui.yml").read_text(encoding="utf-8"))["info_page"]
    docs = {p.name for p in (ROOT / "docs").iterdir()}

    for key, section in info_page.items():
        name = section.get("meta", {}).get("file", f"{key}.md")
        assert name in docs, f"tab {key!r}: no docs/{name} (names are case-sensitive in the container)"
