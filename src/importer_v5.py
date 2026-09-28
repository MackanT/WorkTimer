"""WorkTimer 5.x (SQLite) → v6: the legacy mapping (docs/v6_plan.md §8).

Deletable once everyone has moved. ``read_v5`` opens a *copy* of a 5.x file
with the old SQLite engine, which first brings any older file to the 5.x
shape; ``transform`` turns its tables into the v6 export shape that
``PgDatabase.import_export`` loads.

The rules (§8):

* A customer's versions (5.x's SCD rows) become one customer and one wage
  period per version — each ending the day before the next begins. Every old
  customer_id maps to the one new customer.
* Snapshots are copied verbatim, never recomputed: duration, wage, bonus;
  cost and user bonus rounded to öre.
* Times: 5.x stores naive local times; they get the user's zone and become
  UTC. In the repeated autumn hour the first occurrence is taken (an entry
  that would then end before it starts ends in the second one); a time in
  the skipped spring hour is read as standard time. Tasks' timestamps were
  UTC already (SQLite's current_timestamp).
* An entry's day is its start's local date — 5.x also cached it (date_key),
  and a start edited later could leave that stale.
* ``git_id = 0`` ("no work item") becomes NULL.
* Tracker tokens the importing server can't read are left out — re-enter them.

Anything the v6 schema would refuse is a *problem*: the import stops with a
list of what to fix in 5.x (its query editor can write). Nothing is guessed.
Informational changes are *notes*.
"""

import logging
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .database import Database
from .pat_crypto import decrypt_pat

SQLITE_HEADER = b"SQLite format 3\x00"
EXPORT_TABLES = ("trackers", "customers", "customer_wages", "projects", "bonuses",
                 "time_entries", "tasks", "saved_queries", "work_items")


@dataclass
class V5Import:
    export: dict
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _quiet() -> logging.Logger:
    log = logging.getLogger("worktimer.import.v5")
    log.handlers = [logging.NullHandler()]
    log.propagate = False
    return log


@contextmanager
def opened(path, pat_key_file=None):
    """The 5.x engine on a normalised *copy* of `path` — the file itself is
    never opened for writing. Pass the 5.x install's .pat_key to read tokens
    encrypted there."""
    with open(path, "rb") as f:
        if f.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
            raise ValueError("Not a WorkTimer 5.x database (not an SQLite file)")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "worktimer.db"
        shutil.copyfile(path, copy)
        if pat_key_file:
            shutil.copyfile(pat_key_file, Path(tmp) / ".pat_key")
        db = Database(str(copy), _quiet())
        try:
            db.initialize_db()  # the old engine normalises older files first
            yield db
        finally:
            db.close()


def read_v5(path, pat_key_file=None) -> dict:
    """The tables of a 5.x file. Tracker tokens come back as plaintext, or
    None where unreadable (column ``pat_unreadable`` marks those)."""
    with opened(path, pat_key_file) as db:
        tables = db.read_tables()
        trackers = tables["trackers"]
        if not trackers.empty:
            stored = trackers["pat_token"].tolist()
            readable = [decrypt_pat(v, db.db_file, db.log_engine) or None if v else None
                        for v in stored]
            trackers["pat_token"] = readable
            trackers["pat_unreadable"] = [bool(s) and not r for s, r in zip(stored, readable)]
    return tables


def _rows(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _date(value) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _naive(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("T", " "))
    except ValueError:
        return None


def _money(value, places: str = "0.01") -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal(places), ROUND_HALF_UP))


def _work_item(value) -> int | None:
    """A 5.x git_id as a work-item id: 0 means none. Some 5.x rows hold it as
    an 8-byte little-endian BLOB (a numpy int64 that went in through pandas)."""
    if isinstance(value, (bytes, bytearray)) and len(value) == 8:
        value = int.from_bytes(value, "little", signed=True)
    return int(value) if value not in (None, "") and int(value) > 0 else None


def transform(tables: dict, zone: str) -> V5Import:
    """5.x tables (from read_v5) → the v6 export shape, keyed by 5.x ids."""
    tz = ZoneInfo(zone)
    out = {t: [] for t in EXPORT_TABLES}
    result = V5Import(export={"format": "worktimer-5x-import", "tables": out})
    problem, note = result.problems.append, result.notes.append

    def utc(local: datetime, fold: int = 0) -> datetime:
        return local.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)

    def local_iso(value) -> str | None:
        stamp = _naive(value)
        return utc(stamp).isoformat() if stamp else None

    def utc_iso(value) -> str | None:  # values 5.x wrote with current_timestamp
        stamp = _naive(value)
        return stamp.replace(tzinfo=timezone.utc).isoformat() if stamp else None

    # ── trackers ──
    tracker_keys = set()
    unreadable = []
    for r in _rows(tables.get("trackers")):
        tracker_keys.add(r["tracker_id"])
        if r.get("pat_unreadable"):
            unreadable.append(r["tracker_name"])
        itype = r.get("integration_type") or "devops"
        if itype not in ("devops", "jira"):
            problem(f"Tracker '{r['tracker_name']}' has an unknown type '{itype}'")
        out["trackers"].append({
            "key_tracker": r["tracker_id"], "tracker_name": r["tracker_name"],
            "integration_type": itype, "org_url": r.get("org_url"),
            "pat_token": r.get("pat_token"), "token_expires": _date(r.get("token_expires")),
            "created_at": local_iso(r.get("inserted_at")),
        })
    if unreadable:
        note(f"Tracker tokens that couldn't be read here — re-enter them in Settings: "
             f"{', '.join(unreadable)}")

    # ── customers: versions → one customer + wage periods ──
    groups: dict[str, list] = {}
    for r in _rows(tables.get("customers")):
        groups.setdefault(r["customer_name"], []).append(r)
    customer_key, name_key = {}, {}
    for name, versions in groups.items():
        latest = max(versions, key=lambda v: v["customer_id"])
        key = min(v["customer_id"] for v in versions)
        name_key[name] = key
        for v in versions:
            customer_key[v["customer_id"]] = key
        tracker = latest.get("tracker_id")
        if tracker is not None and tracker not in tracker_keys:
            note(f"Customer '{name}' linked to a tracker that no longer exists — unlinked")
            tracker = None
        firsts = [d for d in (_naive(v.get("inserted_at")) for v in versions) if d]
        out["customers"].append({
            "key_customer": key, "customer_name": name, "currency": "SEK",
            "color": latest.get("color") or None, "fk_tracker": tracker,
            "tracker_project": latest.get("tracker_project") or None,
            "expected_work_pct": latest.get("expected_work_pct"),
            "sort_order": int(latest["sort_order"]) if latest.get("sort_order") is not None else 999,
            "is_enabled": any(int(v.get("is_current") or 0) == 1 for v in versions),
            "created_at": utc(min(firsts)).isoformat() if firsts else None,
        })
        periods = []
        for v in sorted(versions, key=lambda v: (_date(v.get("valid_from")) or _date(v.get("start_date"))
                                                 or date.min, v["customer_id"])):
            start = _date(v.get("valid_from")) or _date(v.get("start_date"))
            if start is None:
                problem(f"Customer '{name}' (customer_id {v['customer_id']}) has a wage "
                        "with no start date")
                continue
            if periods and periods[-1][0] == start:
                note(f"Customer '{name}': two wages start on {start} — the later one "
                     f"({v.get('wage')}) is kept")
                periods[-1] = (start, v.get("wage"), v["customer_id"])
            else:
                periods.append((start, v.get("wage"), v["customer_id"]))
        for i, (start, wage, source) in enumerate(periods):
            amount = float(wage or 0)
            if amount != int(round(amount)):
                note(f"Customer '{name}': wage {amount:g} from {start} rounded to "
                     f"{int(round(amount))} (v6 wages are whole units)")
            out["customer_wages"].append({
                "key_customer_wage": source, "fk_customer": key, "wage": int(round(amount)),
                "valid_from": start.isoformat(),
                "valid_to": (periods[i + 1][0] - timedelta(days=1)).isoformat()
                if i + 1 < len(periods) else None,
            })

    # ── projects (a name used twice for one customer is one project) ──
    project_key, by_name = {}, {}
    for r in sorted(_rows(tables.get("projects")), key=lambda r: r["project_id"]):
        customer = customer_key.get(r["customer_id"])
        if customer is None:
            problem(f"Project '{r['project_name']}' (project_id {r['project_id']}) belongs "
                    f"to no customer (customer_id {r['customer_id']})")
            continue
        enabled = int(r.get("is_current") or 0) == 1
        existing = by_name.get((customer, r["project_name"]))
        if existing is not None:
            project_key[r["project_id"]] = existing["key_project"]
            existing["is_enabled"] = existing["is_enabled"] or enabled
            note(f"Project '{r['project_name']}' appears twice for one customer — merged")
            continue
        row = {"key_project": r["project_id"], "fk_customer": customer,
               "project_name": r["project_name"], "bk_work_item": _work_item(r.get("git_id")),
               "is_enabled": enabled,
               "sort_order": int(r["sort_order"]) if r.get("sort_order") is not None else 999}
        by_name[(customer, r["project_name"])] = row
        project_key[r["project_id"]] = r["project_id"]
        out["projects"].append(row)

    placeholders = {}

    def no_project(customer: int, name: str) -> int:
        """A project for entries that lost theirs (5.x re-links what it can)."""
        if customer not in placeholders:
            placeholders[customer] = -customer  # below every 5.x id
            out["projects"].append({"key_project": -customer, "fk_customer": customer,
                                    "project_name": "(no project)", "bk_work_item": None,
                                    "is_enabled": False, "sort_order": 999})
            note(f"Entries of '{name}' without a project are kept under '(no project)'")
        return placeholders[customer]

    # ── time entries ──
    restated = []
    for r in _rows(tables.get("time")):
        tid = r["time_id"]
        project = project_key.get(r.get("project_id"))
        if project is None:
            customer = customer_key.get(r.get("customer_id")) or name_key.get(r.get("customer_name"))
            if customer is None:
                problem(f"Time entry {tid} belongs to no project or customer")
                continue
            project = no_project(customer, r.get("customer_name") or str(customer))
        start = _naive(r.get("start_time"))
        if start is None:
            problem(f"Time entry {tid} has no start time")
            continue
        started = utc(start)
        ended = None
        if r.get("end_time"):
            end = _naive(r["end_time"])
            ended = utc(end) if end else None
            if ended is not None and ended < started:
                ended = utc(end, fold=1)  # across the autumn change: the second occurrence
                if ended < started:
                    problem(f"Time entry {tid} ({r.get('customer_name')} / "
                            f"{r.get('project_name')}) ends ({r['end_time']}) before it starts "
                            f"({r['start_time']}) — fix its end in 5.x's Manage entries, or its "
                            f"query editor: update time set end_time = '<the right time>' "
                            f"where time_id = {tid}")
                    continue
        duration = r.get("total_time")
        if ended is not None and duration is None:
            problem(f"Time entry {tid} is stopped but has no duration")
            continue
        if duration is not None and duration < 0:
            problem(f"Time entry {tid} has a negative duration ({duration:.4f} h)")
            continue
        running = ended is None
        wage = r.get("wage")
        day = int(start.strftime("%Y%m%d"))  # an entry's day is its start's (5.x Reports agree)
        if r.get("date_key") and int(r["date_key"]) != day:
            restated.append(str(tid))
        out["time_entries"].append({
            "key_time_entry": tid, "fk_project": project,
            "started_at": started.isoformat(), "ended_at": ended.isoformat() if ended else None,
            "fk_date": day,
            "duration_hours": None if running else _money(duration, "0.0001"),
            "wage_snapshot": int(round(float(wage))) if wage is not None else None,
            "bonus_pct_snapshot": _money(r.get("bonus") or 0, "0.0001"),
            "cost": None if running else _money(r.get("cost") or 0),
            "user_bonus": None if running else _money(r.get("user_bonus") or 0),
            "bk_work_item": _work_item(r.get("git_id")), "comment": r.get("comment"),
            "created_at": started.isoformat(), "updated_at": started.isoformat(),
        })

    if restated:
        note(f"Entries dated by their start time — 5.x's cached day for them was stale "
             f"(a start edited later): time_id {', '.join(restated)}")

    # ── bonus periods: refused, not guessed, when v6 would reject them ──
    bonuses = sorted(_rows(tables.get("bonus")), key=lambda r: (_date(r.get("start_date")) or date.min))
    for r in bonuses:
        start, end = _date(r.get("start_date")), _date(r.get("end_date"))
        if start is None:
            problem(f"Bonus period {r['bonus_id']} has no start date")
            continue
        if end is not None and end < start:
            problem(f"Bonus period {r['bonus_id']} ends ({end}) before it starts ({start}) — "
                    f"in 5.x's query editor: update bonus set end_date = '<the right date>' "
                    f"where bonus_id = {r['bonus_id']}")
            continue
        out["bonuses"].append({"key_bonus": r["bonus_id"],
                               "bonus_pct": _money(r.get("bonus_percent") or 0, "0.0001"),
                               "valid_from": start.isoformat(),
                               "valid_to": end.isoformat() if end else None})
    ordered = sorted(out["bonuses"], key=lambda b: b["valid_from"])
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier["valid_to"] is None or earlier["valid_to"] >= later["valid_from"]:
            problem(f"Bonus periods {earlier['key_bonus']} (from {earlier['valid_from']}, "
                    f"to {earlier['valid_to'] or 'open'}) and {later['key_bonus']} (from "
                    f"{later['valid_from']}) overlap — end the first before the second begins")

    # ── tasks (names → keys; unknown names are dropped, with a note) ──
    lost = set()
    for r in _rows(tables.get("tasks")):
        customer = name_key.get(r.get("customer_name")) if r.get("customer_name") else None
        if r.get("customer_name") and customer is None:
            lost.add(r["customer_name"])
        project = None
        if r.get("project_name"):
            matches = [p["key_project"] for p in out["projects"]
                       if p["project_name"] == r["project_name"]
                       and (customer is None or p["fk_customer"] == customer)]
            project = matches[0] if len(matches) == 1 else None
            if project is None:
                lost.add(r["project_name"])
            elif customer is None:
                customer = next(p["fk_customer"] for p in out["projects"] if p["key_project"] == project)
        out["tasks"].append({
            "key_task": r["task_id"], "fk_customer": customer, "fk_project": project,
            "fk_parent_task": r.get("parent_task_id"), "title": r.get("title") or "(untitled)",
            "description": r.get("description"), "status": r.get("status") or "To Do",
            "priority": r.get("priority") or "Medium",
            "is_completed": bool(int(r.get("completed") or 0)),
            "assigned_to": r.get("assigned_to"), "due_date": _date(r.get("due_date")),
            "estimated_hours": _money(r.get("estimated_hours") or 0),
            "actual_hours": _money(r.get("actual_hours") or 0),
            "progress_pct": int(r.get("progress_percentage") or 0), "tags": r.get("tags"),
            "completed_at": utc_iso(r.get("completed_at")),
            "created_at": utc_iso(r.get("created_at")), "updated_at": utc_iso(r.get("updated_at")),
        })
    if lost:
        note(f"Tasks named customers or projects that don't exist; imported without them: "
             f"{', '.join(sorted(map(str, lost)))}")

    # ── saved queries: the user's own (5.x's defaults make way for v6's) ──
    custom = [r for r in _rows(tables.get("queries")) if not int(r.get("is_default") or 0)]
    for r in custom:
        out["saved_queries"].append({"query_name": r["query_name"], "query_sql": r["query_sql"]})
    if custom:
        note(f"Saved queries use 5.x's tables and SQLite's dialect — rewrite them for v6: "
             f"{', '.join(r['query_name'] for r in custom)}")

    # ── cached work items (the tracker sync refreshes them anyway) ──
    items = {}
    for r in _rows(tables.get("devops")):
        customer = name_key.get(r.get("customer_name"))
        if customer is None or r.get("id") is None:
            continue
        changed = r.get("changed_date")
        items[(customer, int(r["id"]))] = {
            "fk_customer": customer, "bk_work_item": int(r["id"]),
            "bk_parent_work_item": _work_item(r.get("parent_id")), "item_type": r.get("type"),
            "title": r.get("title"), "state": r.get("state"), "board_column": r.get("board_column"),
            "is_done": bool(int(r.get("board_column_done") or 0)),
            "assigned_to": r.get("assigned_to"),
            "changed_at": pd.to_datetime(changed, utc=True).isoformat() if changed else None,
            "priority": int(r["priority"]) if r.get("priority") is not None else None,
            "description_text": r.get("description"),
        }
    out["work_items"] = list(items.values())
    return result


def totals(tables: dict) -> pd.DataFrame:
    """Per customer, as 5.x reports it (by the entries' customer name):
    entries, hours and cost — each entry's cost rounded to öre, as imported."""
    rows = {}
    for r in _rows(tables.get("time")):
        t = rows.setdefault(r.get("customer_name"), [0, Decimal(0), Decimal(0)])
        t[0] += 1
        if r.get("end_time"):
            t[1] += Decimal(_money(r.get("total_time") or 0, "0.0001"))
            t[2] += Decimal(_money(r.get("cost") or 0))
    return pd.DataFrame([(c, n, float(h), float(k)) for c, (n, h, k) in sorted(rows.items(), key=lambda x: str(x[0]))],
                        columns=["customer", "entries", "hours", "cost"])
