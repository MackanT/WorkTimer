"""Characterisation tests: the billing core, pinned as it behaves in 5.1.x.

These are the oracle for the Postgres port (docs/v6_implementation.md,
Phase 2). The new data layer must pass them unchanged, except for two
deliberate, reviewed diffs:

* cost is rounded to öre once, from the exact duration (v6_plan §4), and
* wage is looked up by the entry's date instead of the customer version it was
  created against (v6_plan §3) — see
  ``test_backdated_entry_gets_current_wage_but_bonus_by_date``.

Rules for this file:

* Behaviour is driven through public ``Database`` methods only.
* The only SQL is in ``_entries`` and ``_calendar`` — the single place to
  repoint when the schema is renamed.
* Tolerances express the business contract, not float noise. Today's julianday
  arithmetic stores a clean 1-hour entry at 1,200/h as 1199.999996; Postgres
  ``numeric`` will be exact. Either way the invoice agrees to the öre.
"""

from datetime import datetime, timedelta

import pytest

HOURS = 1e-6  # ≈ 3.6 ms
MONEY = 0.005  # half an öre


def _hours(value):
    return pytest.approx(value, abs=HOURS)


def _money(value):
    return pytest.approx(value, abs=MONEY)


# ── helpers ─────────────────────────────────────────────────────────────────


def _acme(db) -> None:
    """Acme at 1000/h from 2026-01-01, with one project: Build."""
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")


def _ids(db, customer: str, project: str) -> tuple[int, int]:
    """(customer_id, project_id) for the customer's *current* version."""
    df = db.get_data_input_list()
    row = df[
        (df.customer_name == customer)
        & (df.c_current == 1)
        & (df.project_name == project)
    ]
    assert len(row) == 1, f"expected one current row for {customer}/{project}"
    return int(row.iloc[0].customer_id), int(row.iloc[0].project_id)


def _entries(db) -> list[dict]:
    """Billing fields of every time entry, oldest first."""
    return db.fetch_query(
        """
        select time_id, customer_id, project_id, date_key,
               total_time, wage, bonus, cost, user_bonus
        from time
        order by time_id
        """
    ).to_dict("records")


def _calendar(db, first: str, last: str) -> dict[str, dict]:
    """Rows of the dates dimension, keyed by ISO date."""
    df = db.fetch_query(
        "select date, year, week from dates where date between ? and ? order by date",
        (first, last),
    )
    return {r["date"]: r for r in df.to_dict("records")}


def _tracker_row(db, customer: str, project: str, first: str, last: str):
    """The time tracker's aggregate for one customer/project, or None."""
    df = db.get_customer_ui_list(first, last)
    row = df[(df.customer_name == customer) & (df.project_name == project)]
    return None if row.empty else row.iloc[0]


# ── duration, cost, bonus ───────────────────────────────────────────────────


def test_entry_duration_cost_and_bonus(db):
    db.insert_bonus("2026-01-01", 10)
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")

    db.insert_manual_time_row(cid, pid, "2026-09-01 09:00", "2026-09-01 10:30")

    [e] = _entries(db)
    assert e["total_time"] == _hours(1.5)
    assert e["wage"] == 1000
    assert e["bonus"] == pytest.approx(0.10)
    assert e["cost"] == _money(1500.00)
    assert e["user_bonus"] == _money(150.00)


def test_entry_spanning_midnight_is_dated_by_its_start(db):
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")

    db.insert_manual_time_row(cid, pid, "2026-09-01 23:30", "2026-09-02 01:00")

    [e] = _entries(db)
    assert e["date_key"] == 20260901
    assert e["total_time"] == _hours(1.5)


# ── wage snapshots ──────────────────────────────────────────────────────────


def test_wage_change_does_not_alter_historical_cost(db):
    """The core billing invariant (v6_plan §3): an entry keeps the wage it was
    logged at, whatever happens to the customer's wage afterwards."""
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-08-03 09:00", "2026-08-03 11:00")

    db.insert_customer("Acme", "2026-09-01", 1200)  # raise → new version
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-09-02 09:00", "2026-09-02 11:00")

    before, after = _entries(db)
    assert before["wage"] == 1000
    assert before["cost"] == _money(2000.00)
    assert after["wage"] == 1200
    assert after["cost"] == _money(2400.00)


def test_editing_an_entry_reprices_it_at_its_own_snapshot(db):
    """An edit made after a raise re-prices the entry at the wage it was
    logged at, not the customer's current wage."""
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-08-03 09:00", "2026-08-03 11:00")
    db.insert_customer("Acme", "2026-09-01", 1200)

    [e] = _entries(db)
    db.update_time_entry(e["time_id"], end_time="2026-08-03 12:00")

    [e] = _entries(db)
    assert e["total_time"] == _hours(3.0)
    assert e["wage"] == 1000
    assert e["cost"] == _money(3000.00)


def test_backdated_entry_gets_current_wage_but_bonus_by_date(db):
    """PINNED CURRENT BEHAVIOUR — changes deliberately in Phase 2.

    Today an entry takes its wage from the customer version it is created
    against (the current one, in the UI) but its bonus by its own date. So
    hours back-dated to August after a September raise are billed at the
    September wage with the August bonus.

    v6_plan §3 moves wage to a lookup by the entry's date. When that lands the
    expected wage here becomes 1000 and the cost 1000.00 — update this test as
    a reviewed diff, not a silent fix.
    """
    db.insert_bonus("2026-01-01", 10)
    _acme(db)
    db.insert_customer("Acme", "2026-09-10", 1200)
    db.insert_bonus("2026-09-10", 20)
    cid, pid = _ids(db, "Acme", "Build")

    db.insert_manual_time_row(cid, pid, "2026-08-15 09:00", "2026-08-15 10:00")

    [e] = _entries(db)
    assert e["wage"] == 1200  # the current version's wage, not August's 1000
    assert e["bonus"] == pytest.approx(0.10)  # August's bonus, by date
    assert e["cost"] == _money(1200.00)
    assert e["user_bonus"] == _money(120.00)


# ── bonus periods ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "day, expected",
    [
        ("2025-12-31", 0.00),  # before any bonus period
        ("2026-01-01", 0.10),  # first day of the first period (inclusive)
        ("2026-05-31", 0.10),  # last day of the first period (inclusive)
        ("2026-06-01", 0.20),  # first day of the next period
        ("2030-06-01", 0.20),  # the open-ended current period
    ],
)
def test_bonus_is_looked_up_by_the_entry_date(db, day, expected):
    db.insert_bonus("2026-01-01", 10)
    db.insert_bonus("2026-06-01", 20)  # closes the first period on 2026-05-31
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")

    db.insert_manual_time_row(cid, pid, f"{day} 09:00", f"{day} 10:00")

    [e] = _entries(db)
    assert e["bonus"] == pytest.approx(expected)
    assert e["user_bonus"] == _money(1000 * expected)


# ── timer path ──────────────────────────────────────────────────────────────


def test_stopping_a_timer_with_backdated_end_and_reassigned_project(db):
    _acme(db)
    db.insert_project("Acme", "Support")
    cid, build = _ids(db, "Acme", "Build")
    _, support = _ids(db, "Acme", "Support")

    db.insert_timer_start_row(cid, build, "2026-09-01 09:00")
    db.insert_time_row(cid, build, end_time="2026-09-01 11:00", new_project_id=support)

    [e] = _entries(db)
    assert e["project_id"] == support
    assert e["total_time"] == _hours(2.0)
    assert e["wage"] == 1000
    assert e["cost"] == _money(2000.00)


# ── time tracker totals (get_customer_ui_list) ──────────────────────────────


def test_tracker_totals_span_every_wage_version(db):
    """Totals join entries to customers by *name*, so history logged under an
    old wage version still counts (the 5.0.1 SCD2 fix)."""
    db.insert_bonus("2026-01-01", 10)
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-08-03 09:00", "2026-08-03 11:00")
    db.insert_customer("Acme", "2026-09-01", 1200)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-09-02 09:00", "2026-09-02 11:00")

    row = _tracker_row(db, "Acme", "Build", "20260801", "20260930")
    assert row.total_time == _hours(4.0)
    assert row.user_bonus == _money(2 * 1000 * 0.10 + 2 * 1200 * 0.10)


def test_tracker_totals_filter_by_entry_date(db):
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-08-31 09:00", "2026-08-31 10:00")
    db.insert_manual_time_row(cid, pid, "2026-09-01 09:00", "2026-09-01 11:00")

    september = _tracker_row(db, "Acme", "Build", "20260901", "20260930")
    assert september.total_time == _hours(2.0)
    # A project with no entries in the range is still listed, at zero.
    october = _tracker_row(db, "Acme", "Build", "20261001", "20261031")
    assert october.total_time == 0


def test_running_timer_counts_live_elapsed_time(db):
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    now = datetime.now()
    two_hours_ago = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

    db.insert_timer_start_row(cid, pid, two_hours_ago)

    first = (now - timedelta(days=1)).strftime("%Y%m%d")  # safe across midnight
    row = _tracker_row(db, "Acme", "Build", first, now.strftime("%Y%m%d"))
    assert row.total_time == pytest.approx(2.0, abs=0.02)  # shown to 2 decimals


def test_disabled_customer_leaves_the_tracker_and_returns_with_its_history(db):
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-09-01 09:00", "2026-09-01 11:00")

    db.disable_customer("Acme")
    assert _tracker_row(db, "Acme", "Build", "20260901", "20260930") is None

    db.enable_customer("Acme")
    row = _tracker_row(db, "Acme", "Build", "20260901", "20260930")
    assert row.total_time == _hours(2.0)


def test_renamed_customer_keeps_all_history(db):
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-08-03 09:00", "2026-08-03 11:00")
    db.insert_customer("Acme", "2026-09-01", 1200)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-09-02 09:00", "2026-09-02 10:00")

    db.update_customer("Acme", "Acme AB")

    assert _tracker_row(db, "Acme", "Build", "20260801", "20260930") is None
    row = _tracker_row(db, "Acme AB", "Build", "20260801", "20260930")
    assert row.total_time == _hours(3.0)


def test_deleted_entry_drops_out_of_totals(db):
    """Holds for today's hard delete and Phase 2's soft delete alike."""
    _acme(db)
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-09-01 09:00", "2026-09-01 11:00")
    db.insert_manual_time_row(cid, pid, "2026-09-02 09:00", "2026-09-02 10:00")

    db.delete_time_entry(_entries(db)[0]["time_id"])

    row = _tracker_row(db, "Acme", "Build", "20260901", "20260930")
    assert row.total_time == _hours(1.0)


# ── calendar ────────────────────────────────────────────────────────────────


def test_week_numbers_are_iso_across_new_year(db):
    """2026 has 53 ISO weeks. `week` is ISO but `year` is the *calendar* year,
    so 1-3 January 2027 read as "2027, week 53" — the split v6_plan §5 fixes by
    adding `iso_year`. The existing columns keep these values."""
    cal = _calendar(db, "2026-12-27", "2027-01-04")
    assert cal["2026-12-27"]["week"] == 52
    assert cal["2026-12-28"]["week"] == 53
    assert cal["2027-01-03"]["week"] == 53
    assert cal["2027-01-04"]["week"] == 1
    assert (cal["2027-01-01"]["year"], cal["2027-01-01"]["week"]) == (2027, 53)
