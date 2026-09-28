"""Characterisation tests: the Reports page's queries, pinned as they behave in
5.1.x now that they live in the data layer (``Database.report_*``).

Part of the Postgres-port oracle (docs/v6_implementation.md, Phase 0.2): the
new data layer must return the same numbers. Everything here goes through
public methods — there is no SQL in this file.

Two pinned quirks are reviewed diffs on Postgres (Phase 2, both decided as
fixes) — see ``test_rounding_per_project_and_same_named_projects`` and
``test_rounding_per_work_item_and_how_untagged_time_was_logged``.
"""

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.backends("sqlite", "postgres")

HOURS = 1e-6  # ≈ 3.6 ms
MONEY = 0.005  # half an öre

SEPTEMBER = ("2026-09-01", "2026-09-30")
AUGUST = ("2026-08-01", "2026-08-31")
EMPTY = ("2027-01-01", "2027-01-31")


def _hours(value):
    return pytest.approx(value, abs=HOURS)


def _money(value):
    return pytest.approx(value, abs=MONEY)


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


@pytest.fixture
def seeded(db):
    """Three customers; September has entries on four days, one entry starts on
    31 August and runs into September, and Gamma is disabled after logging
    time. Durations are chosen so no two groups tie in any ranking.

    September:  Acme  Build    2.00 h  (#101)   09-01
                Acme  Build    1.50 h  (#101)   09-02
                Acme  Support  0.75 h  (none)   09-02
                Beta  Build    1.00 h  (#303)   09-03
                Beta  Ops      3.00 h  (#202)   09-03
                Gamma Misc     1.25 h  (none)   09-04
    August:     Acme  Build    2.00 h  (#101)   08-31 23:00 → 09-01 01:00
    """
    db.insert_customer("Acme", "2026-01-01", 1000, expected_work_pct=50, color="#ff0000")
    db.insert_customer("Beta", "2026-01-01", 800, expected_work_pct=30, color="#00ff00")
    db.insert_customer("Gamma", "2026-01-01", 500)
    for customer, project in [
        ("Acme", "Build"), ("Acme", "Support"),
        ("Beta", "Build"), ("Beta", "Ops"),
        ("Gamma", "Misc"),
    ]:
        db.insert_project(customer, project)

    for customer, project, start, end, git_id in [
        ("Acme", "Build", "2026-09-01 09:00", "2026-09-01 11:00", 101),
        ("Acme", "Build", "2026-09-02 09:00", "2026-09-02 10:30", 101),
        ("Acme", "Support", "2026-09-02 13:00", "2026-09-02 13:45", None),
        ("Beta", "Build", "2026-09-03 08:00", "2026-09-03 09:00", 303),
        ("Beta", "Ops", "2026-09-03 09:00", "2026-09-03 12:00", 202),
        ("Gamma", "Misc", "2026-09-04 10:00", "2026-09-04 11:15", None),
        ("Acme", "Build", "2026-08-31 23:00", "2026-09-01 01:00", 101),
    ]:
        db.insert_manual_time_row(*_ids(db, customer, project), start, end, git_id=git_id)

    db.disable_customer("Gamma")
    return db


def _pairs(df, *cols):
    return [tuple(r) for r in df[list(cols)].itertuples(index=False)]


# ── current customers ───────────────────────────────────────────────────────


def test_current_customers_exclude_disabled_and_are_ordered_by_name(seeded):
    df = seeded.get_current_customers()

    assert df["customer_name"].tolist() == ["Acme", "Beta"]
    assert df["color"].tolist() == ["#ff0000", "#00ff00"]
    assert df["expected_work_pct"].tolist() == [50, 30]


# ── totals ──────────────────────────────────────────────────────────────────


def test_totals_for_all_customers(seeded):
    """"All" includes a disabled customer's time (Gamma), even though disabled
    customers cannot be picked in the filter."""
    [t] = seeded.report_totals(*SEPTEMBER).to_dict("records")

    assert t["h"] == _hours(9.5)
    assert t["c"] == _money(2000 + 1500 + 750 + 800 + 2400 + 625)
    assert t["cth"] == _hours(9.5)
    assert t["n"] == 6
    assert t["d"] == 4


def test_totals_for_selected_customers(seeded):
    [t] = seeded.report_totals(*SEPTEMBER, ["Acme"]).to_dict("records")

    assert t["h"] == _hours(4.25)
    assert t["c"] == _money(4250)
    assert t["n"] == 3
    assert t["d"] == 2


def test_entries_are_reported_on_the_day_they_start(seeded):
    """The 23:00–01:00 entry counts wholly in August, none of it in September."""
    [t] = seeded.report_totals(*AUGUST).to_dict("records")

    assert t["h"] == _hours(2.0)
    assert t["c"] == _money(2000)
    assert t["n"] == 1


def test_totals_for_an_empty_range_are_zero(seeded):
    [t] = seeded.report_totals(*EMPTY).to_dict("records")

    assert (t["h"], t["c"], t["cth"], t["n"], t["d"]) == (0, 0, 0, 0, 0)


def test_running_timer_counts_in_hours_but_not_in_cost(db):
    """A running timer adds live hours but has no cost or completed hours yet —
    the page derives its blended rate from completed hours for that reason."""
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    now = datetime.now()
    db.insert_timer_start_row(
        *_ids(db, "Acme", "Build"),
        (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
    )

    first = (now - timedelta(days=1)).strftime("%Y-%m-%d")  # safe across midnight
    [t] = db.report_totals(first, now.strftime("%Y-%m-%d")).to_dict("records")

    assert t["h"] == pytest.approx(2.0, abs=0.01)
    assert t["c"] == 0
    assert t["cth"] == 0
    assert t["n"] == 1


# ── breakdowns ──────────────────────────────────────────────────────────────


def test_hours_by_project_keep_same_named_projects_apart(seeded):
    df = seeded.report_hours_by_project(*SEPTEMBER)

    assert _pairs(df, "k", "cust") == [
        ("Build", "Acme"), ("Ops", "Beta"), ("Misc", "Gamma"),
        ("Build", "Beta"), ("Support", "Acme"),
    ]
    assert df["h"].tolist() == [_hours(3.5), _hours(3.0), _hours(1.25),
                                _hours(1.0), _hours(0.75)]


def test_hours_by_customer(seeded):
    df = seeded.report_hours_by_customer(*SEPTEMBER)

    assert df["k"].tolist() == ["Acme", "Beta", "Gamma"]
    assert df["h"].tolist() == [_hours(4.25), _hours(4.0), _hours(1.25)]


def test_hours_by_day(seeded):
    df = seeded.report_hours_by_day(*SEPTEMBER)

    assert df["d"].tolist() == ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
    assert df["h"].tolist() == [_hours(2.0), _hours(2.25), _hours(4.0), _hours(1.25)]


def test_hours_by_work_item_exclude_untagged_time(seeded):
    df = seeded.report_hours_by_work_item(*SEPTEMBER)

    assert _pairs(df, "gid", "cust") == [(101, "Acme"), (202, "Beta"), (303, "Beta")]
    assert df["h"].tolist() == [_hours(3.5), _hours(3.0), _hours(1.0)]


def test_breakdowns_honour_the_customer_filter(seeded):
    df = seeded.report_hours_by_customer(*SEPTEMBER, ["Beta"])

    assert df["k"].tolist() == ["Beta"]


def test_money_per_currency_matches_the_totals_for_one_currency(seeded):
    """All SEK (Postgres's default; SQLite has no currencies): one row, the
    same hours and cost as the totals."""
    [a] = seeded.report_amounts(*SEPTEMBER).to_dict("records")
    [t] = seeded.report_totals(*SEPTEMBER).to_dict("records")

    assert (a["h"], a["c"], a["cth"]) == (t["h"], t["c"], t["cth"])
    assert a["currency"] == ("SEK" if seeded.backend == "postgres" else None)


# ── billing-rounding units ──────────────────────────────────────────────────


def _sorted_hours(df):
    return sorted(round(h, 6) for h in df["h"])


def test_rounding_per_entry_gives_one_unit_per_entry(seeded):
    df = seeded.report_hours_for_rounding(*SEPTEMBER, [], "entry")

    assert _sorted_hours(df) == [0.75, 1.0, 1.25, 1.5, 2.0, 3.0]


def test_rounding_per_work_item_pools_all_untagged_time(seeded):
    """Untagged manual entries are one unit across every customer
    (Acme 0.75 + Gamma 1.25)."""
    df = seeded.report_hours_for_rounding(*SEPTEMBER, [], "work_item")

    assert _sorted_hours(df) == [1.0, 2.0, 3.0, 3.5]


def test_rounding_per_work_item_and_how_untagged_time_was_logged(db):
    """REVIEWED DIFF (Phase 2) — decided: untagged time is one unit.

    SQLite stores "no work item" as 0 from a manual entry but NULL from a
    stopped timer, and rounding groups by COALESCE(git_id, -1) — so untagged
    time rounds as two units depending on how it was logged. Postgres stores
    NULL everywhere (v6_plan §4), which pools them.
    """
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    cid, pid = _ids(db, "Acme", "Build")
    db.insert_manual_time_row(cid, pid, "2026-09-01 09:00", "2026-09-01 10:00")
    db.insert_timer_start_row(cid, pid, "2026-09-02 09:00")
    db.insert_time_row(cid, pid, end_time="2026-09-02 11:00")

    df = db.report_hours_for_rounding(*SEPTEMBER, [], "work_item")

    assert _sorted_hours(df) == ([1.0, 2.0] if db.backend == "sqlite" else [3.0])


def test_rounding_per_project_and_same_named_projects(seeded):
    """REVIEWED DIFF (Phase 2) — decided: each project rounds on its own.

    SQLite's rounding "per project" groups by project *name* only, so Acme's
    Build (3.5 h) and Beta's Build (1.0 h) round as a single 4.5 h unit —
    while the by-project chart keeps them apart. Postgres groups by project.
    """
    df = seeded.report_hours_for_rounding(*SEPTEMBER, [], "project")

    expected = ([0.75, 1.25, 3.0, 4.5] if seeded.backend == "sqlite"
                else [0.75, 1.0, 1.25, 3.0, 3.5])
    assert _sorted_hours(df) == expected
