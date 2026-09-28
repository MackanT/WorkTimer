"""What the page smoke tests share (tests/test_smoke_pages.py on SQLite,
tests/test_smoke_pages_pg.py on Postgres): the pages, the seed data — written
through the public data-layer API, so it seeds either backend — and the wait
for a page to finish building."""

import asyncio
from datetime import datetime, timedelta

import pandas as pd
from nicegui import background_tasks

PAGES = {  # path -> text proving the page rendered seeded data (None: build check only)
    "/time": "Acme",
    "/tasks": "Write report",
    "/query_editor": "hours by customer",
    "/reports": None,
    "/board": None,
    "/notepad": None,
    "/log": None,
    "/info": None,
    "/settings": None,
}


def seed(db) -> None:
    """Customers (one with a raise, one disabled), projects (one disabled),
    completed entries across two months, a running timer, a bonus, tasks, a
    saved query and cached work items."""
    db.insert_bonus("2026-01-01", 10)
    db.insert_customer("Acme", "2026-01-01", 1000, tracker_project="PLAT",
                       expected_work_pct=50, color="#e11d48")
    db.insert_customer("Beta", "2026-01-01", 850, expected_work_pct=30, color="#0ea5e9")
    db.insert_customer("Gamma", "2026-01-01", 700)
    for customer, project in [("Acme", "Build"), ("Acme", "Support"), ("Beta", "Ops"),
                              ("Beta", "Old"), ("Gamma", "Misc")]:
        db.insert_project(customer, project)

    def ids(customer, project):
        df = db.get_data_input_list()
        row = df[(df.customer_name == customer) & (df.project_name == project)
                 & (df.c_current == 1)].iloc[0]
        return int(row.customer_id), int(row.project_id)

    now = datetime.now()
    for days, customer, project, hours, git_id in [
        (40, "Acme", "Build", 3, 101), (33, "Acme", "Support", 1.5, None),
        (25, "Beta", "Ops", 4, 202), (12, "Acme", "Build", 2.5, 101),
        (5, "Beta", "Ops", 2, None), (2, "Gamma", "Misc", 1, None),
    ]:
        start = (now - timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)
        db.insert_manual_time_row(*ids(customer, project), f"{start:%Y-%m-%d %H:%M}",
                                  f"{start + timedelta(hours=hours):%Y-%m-%d %H:%M}", git_id=git_id)
    db.insert_customer("Acme", f"{now - timedelta(days=10):%Y-%m-%d}", 1150)  # a raise
    db.insert_timer_start_row(*ids("Beta", "Ops"), f"{now - timedelta(hours=1):%Y-%m-%d %H:%M}")
    db.disable_project("Beta", "Old")
    db.disable_customer("Gamma")
    db.insert_task("Write report", priority="High", due_date=f"{now + timedelta(days=3):%Y-%m-%d}",
                   customer_name="Acme", project_name="Build")
    db.insert_task("Fix login", priority="Critical", customer_name="Beta", project_name="Ops")
    db.insert_saved_query("hours by customer",
                          "select customer_name, sum(total_time) as h from time group by customer_name")
    db.update_devops_data(pd.DataFrame([
        {"customer_name": "Acme", "type": "User Story", "id": 101, "title": "Login flow",
         "state": "Active", "changed_date": "2026-09-01T10:00:00"},
        {"customer_name": "Acme", "type": "Task", "id": 102, "title": "Session timeout",
         "state": "New", "parent_id": 101, "changed_date": "2026-09-20T10:00:00"},
    ]), mode="append")


async def page_built():
    """Every page is `async def`, so ui.sub_pages builds it in a background
    task that can outlive user.open(). Wait for it to finish, then yield once
    so NiceGUI's done-callback logs any exception — which the user fixture
    turns into a failure."""
    for _ in range(100):
        pending = [t for t in background_tasks.running_tasks
                   if t.get_name().startswith("building sub_page") and not t.done()]
        if not pending:
            break
        await asyncio.wait(pending, timeout=0.1)
    else:
        raise AssertionError("sub page still building after 10 s")
    await asyncio.sleep(0)
