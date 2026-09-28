"""Regression (5.1.2): the Time Tracker's "sort by usage" after a raise.

It summed the last 60 days by time.customer_id — but an entry keeps the
customer version it was logged under, so right after a raise the current id
saw next to nothing and the sort left the order unchanged.
"""

from datetime import datetime, timedelta


def _current_ids(db, customer: str) -> tuple[int, dict]:
    cid = int(db.fetch_query(
        "select customer_id from customers where customer_name = ? and is_current = 1",
        (customer,),
    ).iloc[0, 0])
    projects = db.fetch_query(
        "select project_name, project_id from projects where customer_id = ?", (cid,)
    )
    return cid, dict(zip(projects.project_name, projects.project_id.astype(int)))


def _usage(db, customer: str) -> dict:
    cid, projects = _current_ids(db, customer)
    rows = db.get_recent_project_hours(cid)
    by_id = {int(r.project_id): round(float(r.h), 2) for r in rows.itertuples()}
    return {name: by_id[pid] for name, pid in projects.items() if pid in by_id}


def _log(db, customer, project, day, start, end):
    cid, projects = _current_ids(db, customer)
    db.insert_manual_time_row(cid, projects[project], f"{day} {start}", f"{day} {end}")


def test_usage_includes_entries_logged_before_a_raise(db):
    day = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    db.insert_customer("Acme", "2026-01-01", 1000)
    for p in ("Build", "Support"):
        db.insert_project("Acme", p)
    _log(db, "Acme", "Build", day, "09:00", "12:00")
    _log(db, "Acme", "Support", day, "13:00", "14:00")

    db.insert_customer("Acme", datetime.now().strftime("%Y-%m-%d"), 1200)  # raise

    assert _usage(db, "Acme") == {"Build": 3.0, "Support": 1.0}


def test_usage_is_per_customer_and_last_60_days(db):
    recent = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    old = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    for c in ("Acme", "Beta"):
        db.insert_customer(c, "2025-01-01", 1000)
        db.insert_project(c, "Work")
    _log(db, "Acme", "Work", recent, "09:00", "11:00")
    _log(db, "Acme", "Work", old, "09:00", "17:00")
    _log(db, "Beta", "Work", recent, "09:00", "10:00")

    assert _usage(db, "Acme") == {"Work": 2.0}
