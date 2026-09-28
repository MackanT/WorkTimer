"""Import into the Postgres WorkTimer (v6 Phase 4, docs/v6_plan.md §8).

Two kinds of file: a WorkTimer 5.x database (SQLite, through the legacy
mapping in src/importer_v5.py) and a v6 export (the app's own backup,
.json.gz). Two steps, then a report:

1. ``prepare`` — read, transform and check; nothing is written. Problems
   (data v6 would refuse) stop here, with what to fix.
2. ``load`` — one transaction, into an empty account unless ``replace``.
3. The report: entries, hours and cost per customer, before and after, side
   by side — the numbers must match, to the öre.

Command line (Phase 5's weekly import into staging), connecting as the app:
    DATABASE_URL=… python -m src.importer FILE [--replace] [--dry-run]
        [--check-reports] [--pat-key FILE]
Exit codes: 0 everything matches, 1 problems in the file, 2 stopped,
3 imported but numbers differ. The last line is "RESULT: …".
"""

import argparse
import gzip
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from . import clock, importer_v5
from .pat_crypto import decrypt_pat
from .pg_database import PgDatabase

GZIP_HEADER = b"\x1f\x8b"


@dataclass
class Prepared:
    kind: str                  # "5.x database" or "v6 export"
    export: dict
    before: pd.DataFrame       # per customer: entries, hours, cost
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {t: len(rows) for t, rows in self.export.get("tables", {}).items()}


def _export_totals(export: dict) -> pd.DataFrame:
    """Per customer from export-shaped data (deleted entries excluded)."""
    tables = export.get("tables", {})
    names = {c["key_customer"]: c["customer_name"] for c in tables.get("customers", [])}
    owner = {p["key_project"]: names.get(p["fk_customer"]) for p in tables.get("projects", [])}
    rows = {}
    for e in tables.get("time_entries", []):
        if e.get("deleted_at"):
            continue
        t = rows.setdefault(owner.get(e["fk_project"]), [0, Decimal(0), Decimal(0)])
        t[0] += 1
        t[1] += Decimal(str(e.get("duration_hours") or 0))
        t[2] += Decimal(str(e.get("cost") or 0))
    return pd.DataFrame([(c, n, float(h), float(k)) for c, (n, h, k) in
                         sorted(rows.items(), key=lambda x: str(x[0]))],
                        columns=["customer", "entries", "hours", "cost"])


def prepare(path, db: PgDatabase, pat_key_file=None) -> Prepared:
    """Read and check a file for import into `db`'s account — nothing is written."""
    with open(path, "rb") as f:
        head = f.read(16)
    if head.startswith(importer_v5.SQLITE_HEADER):
        tables = importer_v5.read_v5(path, pat_key_file)
        with db._tx() as conn:
            zone = db._timezone(conn).key
        result = importer_v5.transform(tables, zone)
        return Prepared("5.x database", result.export, importer_v5.totals(tables),
                        result.problems, result.notes)
    if head.startswith(GZIP_HEADER):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            export = json.load(f)
        if export.get("format") != PgDatabase.EXPORT_FORMAT:
            raise ValueError("Not a WorkTimer export")
        if export.get("format_version") != 1:
            raise ValueError(f"Export format {export.get('format_version')} is newer than "
                             "this WorkTimer — update it first")
        notes, unreadable = [], []
        for tracker in export["tables"].get("trackers", []):  # tokens: this server's key
            stored = tracker.get("pat_token")
            tracker["pat_token"] = decrypt_pat(stored, db.db_file, db.log_engine) or None if stored else None
            if stored and not tracker["pat_token"]:
                unreadable.append(tracker["tracker_name"])
        if unreadable:
            notes.append(f"Tracker tokens that couldn't be read here — re-enter them in "
                         f"Settings: {', '.join(unreadable)}")
        return Prepared("v6 export", export, _export_totals(export), [], notes)
    raise ValueError("Not a WorkTimer 5.x database or v6 export")


def report(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """Before and after, side by side; `match` when entries, hours (to 0.0001 h
    per entry) and cost (to the öre) agree."""
    both = before.merge(after, on="customer", how="outer", suffixes=("_before", "_after")).fillna(0)
    both["match"] = ((both["entries_before"] == both["entries_after"])
                     & ((both["hours_before"] - both["hours_after"]).abs()
                        <= 0.0001 * both["entries_before"].clip(lower=1))
                     & ((both["cost_before"] - both["cost_after"]).abs() < 0.005))
    return both[["customer", "entries_before", "entries_after", "hours_before", "hours_after",
                 "cost_before", "cost_after", "match"]]


def compare_reports(v5_path, db: PgDatabase, today: date | None = None) -> pd.DataFrame:
    """Month by month from the first 5.x entry to this month: the Reports
    page's totals (hours, cost, entries, days) from 5.x and from Postgres —
    the report queries themselves, not just the stored rows. Hours may drift
    by a running timer's seconds; cost by < half an öre per entry."""
    today = today or clock.today_local()
    rows = []
    with importer_v5.opened(v5_path) as v5:
        first = v5.get_first_entry_date().iloc[0]["min_date"]
        if not first:
            return pd.DataFrame(columns=["month", "match"])
        month = date.fromisoformat(first).replace(day=1)
        while month <= today:
            last = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            old = v5.report_totals(month.isoformat(), last.isoformat()).iloc[0]
            new = db.report_totals(month.isoformat(), last.isoformat()).iloc[0]
            n = int(old["n"])
            rows.append({
                "month": month.strftime("%Y-%m"),
                "hours_5x": round(float(old["h"]), 4), "hours_v6": round(float(new["h"]), 4),
                "cost_5x": round(float(old["c"]), 2), "cost_v6": round(float(new["c"]), 2),
                "entries_5x": n, "entries_v6": int(new["n"]),
                "days_5x": int(old["d"]), "days_v6": int(new["d"]),
                "match": (n == int(new["n"]) and int(old["d"]) == int(new["d"])
                          and abs(float(old["h"]) - float(new["h"])) <= 0.0001 * max(n, 1) + 0.02
                          and abs(float(old["c"]) - float(new["c"])) <= 0.005 * max(n, 1)),
            })
            month = last + timedelta(days=1)
    return pd.DataFrame(rows)


def load(prepared: Prepared, db: PgDatabase, replace: bool = False) -> pd.DataFrame:
    """Import a prepared file (refused while it has problems); the report."""
    if prepared.problems:
        raise ValueError("Fix these first:\n" + "\n".join(f"- {p}" for p in prepared.problems))
    db.import_export(prepared.export, replace=replace)
    return report(prepared.before, db.import_totals())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.importer",
                                     description="Import a 5.x database or v6 export.")
    parser.add_argument("file")
    parser.add_argument("--replace", action="store_true",
                        help="delete everything in the account first")
    parser.add_argument("--dry-run", action="store_true", help="check only")
    parser.add_argument("--check-reports", action="store_true",
                        help="also compare the Reports totals month by month")
    parser.add_argument("--pat-key", help="the 5.x install's .pat_key, to keep tracker tokens")
    args = parser.parse_args(argv)

    from .pg_connection import PgConfig, Pools

    log = logging.getLogger("worktimer.import")
    db = PgDatabase(Pools(PgConfig.from_env(), max_size=1), log)
    try:
        prepared = prepare(args.file, db, args.pat_key)
        print(f"{prepared.kind}: " + ", ".join(f"{t}: {n}" for t, n in prepared.counts.items() if n))
        for n in prepared.notes:
            print(f"note: {n}")
        for p in prepared.problems:
            print(f"PROBLEM: {p}")
        if prepared.problems:
            print("Nothing imported — fix the problems above in 5.x and try again.")
            print("RESULT: problems in the file")
            return 1
        if args.dry_run:
            print(prepared.before.to_string(index=False))
            print("RESULT: checked (dry run)")
            return 0
        result = load(prepared, db, replace=args.replace)
        print(result.to_string(index=False))
        matched = bool(result["match"].all())
        if args.check_reports and prepared.kind == "5.x database":
            months = compare_reports(args.file, db)
            print(months.to_string(index=False))
            matched = matched and bool(months["match"].all())
        print(f"RESULT: {'match' if matched else 'MISMATCH'}")
        return 0 if matched else 3
    except ValueError as e:
        print(f"Import stopped: {e}", file=sys.stderr)
        print("RESULT: stopped")
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
