"""Per-tracker, per-work-item-type defaults for the add-work-item form
(config/tracker_defaults.yml).

Configured on Settings → Trackers; applied when the add dialog picks or
switches customer or level. Schema:

    trackers:
      "Test (jira)":
        "*":              # applies to every level of this tracker
          priority: 3
        Story:            # level-specific — wins over "*" per field
          state: To Do

A field the selected tracker (or level) doesn't show is simply ignored —
the file stores intent, the form decides relevance.
"""

from pathlib import Path

import yaml

# Fields a tracker default can prefill on the add form.
DEFAULT_FIELDS = ("state", "priority", "board_column", "source", "contact_person")

# The catch-all level key.
ALL_TYPES = "*"

_FILE = "tracker_defaults.yml"


def load_tracker_defaults(config_folder) -> dict:
    """{tracker_name: {level_or_*: {field: value}}} — {} when unconfigured
    or unreadable. A legacy flat entry ({field: value} directly under the
    tracker) is normalised to the "*" level."""
    path = Path(config_folder) / _FILE
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        trackers = data.get("trackers") or {}
        if not isinstance(trackers, dict):
            return {}
        out: dict = {}
        for tname, entry in trackers.items():
            if not isinstance(entry, dict):
                continue
            if entry and all(not isinstance(v, dict) for v in entry.values()):
                out[tname] = {ALL_TYPES: entry}  # legacy flat form
            else:
                out[tname] = {
                    k: v for k, v in entry.items() if isinstance(v, dict)
                }
        return out
    except Exception:
        return {}


def defaults_for(trackers: dict, tracker_name: str, work_item_type) -> dict:
    """The effective {field: value} for one tracker + level: the "*" entry
    overlaid by the level's own entry."""
    entry = trackers.get(tracker_name or "") or {}
    merged = dict(entry.get(ALL_TYPES) or {})
    if work_item_type:
        merged.update(entry.get(str(work_item_type)) or {})
    return merged


def save_tracker_defaults(config_folder, trackers: dict) -> None:
    """Persist the whole {tracker_name: {field: value}} map (empty values
    should be dropped by the caller — absent means 'no default')."""
    path = Path(config_folder) / _FILE
    path.write_text(
        yaml.safe_dump(
            {"trackers": trackers}, allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
