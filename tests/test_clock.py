"""src/clock.py — the one source of "now" for the user's calendar (v6 phase
0.3). Behaviour is unchanged (it returns what the standard library does); the
point is that everything on the user's calendar reads the time here, so
freezing this one module freezes the app's notion of now."""

from datetime import date, datetime, timedelta

from src import clock, helpers


def _ids(db, customer, project):
    df = db.get_data_input_list()
    row = df[(df.customer_name == customer) & (df.c_current == 1) & (df.project_name == project)]
    return int(row.iloc[0].customer_id), int(row.iloc[0].project_id)


def test_clock_returns_what_the_standard_library_does():
    before = datetime.now()
    now = clock.now_local()
    after = datetime.now()
    assert before <= now <= after
    assert now.tzinfo is None  # naive local time, as before

    assert clock.today_local() in {date.today(), date.today() - timedelta(days=1)}


def test_starting_and_stopping_a_timer_read_the_clock(db, monkeypatch):
    db.insert_customer("Acme", "2026-01-01", 1000)
    db.insert_project("Acme", "Build")
    cid, pid = _ids(db, "Acme", "Build")

    monkeypatch.setattr(clock, "now_local", lambda: datetime(2026, 9, 1, 9, 0, 0))
    db.insert_time_row(cid, pid)  # start
    monkeypatch.setattr(clock, "now_local", lambda: datetime(2026, 9, 1, 11, 30, 0))
    db.insert_time_row(cid, pid)  # stop

    [entry] = db.fetch_query(
        "select start_time, end_time, date_key, total_time from time"
    ).to_dict("records")
    assert (entry["start_time"], entry["end_time"]) == ("2026-09-01 09:00:00", "2026-09-01 11:30:00")
    assert entry["date_key"] == 20260901
    assert abs(entry["total_time"] - 2.5) < 1e-6


def test_date_presets_read_the_clock(monkeypatch):
    monkeypatch.setattr(clock, "today_local", lambda: date(2026, 2, 14))  # a Saturday

    assert helpers.get_range_for("Day") == "2026-02-14 - 2026-02-14"
    assert helpers.get_range_for("Week") == "2026-02-09 - 2026-02-15"
    assert helpers.get_range_for("Month") == "2026-02-01 - 2026-02-28"
    assert helpers.get_range_for("Year") == "2026-01-01 - 2026-12-31"
