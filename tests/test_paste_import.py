"""src/paste_import.py — a table pasted from Excel: read, its columns guessed,
its rows turned into entries or into what to fix."""

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from src import paste_import as pi
from src.paste_import import IGNORE

SWEDISH = (
    "Datum\tVecka\tKund\tProjekt\tTimmar\tKommentar\r\n"
    "2026-03-02\t10\tAcme\tPlattform\t7,5\tWorkshop med teamet\r\n"
    "2026-03-03\t10\tBeta AB\tMigrering\t4\tFlytt av databasen\r\n"
    "2026-03-03\t10\tAcme\tPlattform\t3,5\tGranskning\r\n"
)


def _guess(text):
    rows = pi.read_table(text)
    return rows, *pi.guess_columns(rows)


# ── reading the paste ───────────────────────────────────────────────────────


def test_cells_are_trimmed_and_empty_rows_and_columns_dropped():
    rows = pi.read_table("\r\nDate\tHours\t\t\r\n 2026-03-02 \t 7 \t\t\r\n\t\t\t\r\n")

    assert rows == [["Date", "Hours"], ["2026-03-02", "7"]]


def test_a_quoted_cell_keeps_its_line_break_and_tab():
    rows = pi.read_table('Date\tComment\r\n2026-03-02\t"Line one\nline\ttwo ""quoted"""\r\n')

    assert rows[1] == ["2026-03-02", 'Line one\nline\ttwo "quoted"']


def test_too_many_rows_are_refused(monkeypatch):
    monkeypatch.setattr(pi, "MAX_ROWS", 2)
    with pytest.raises(ValueError, match="More than 2 rows"):
        pi.read_table("Date\n" + "2026-03-02\n" * 3)


# ── guessing the columns ────────────────────────────────────────────────────


def test_swedish_headers_name_their_columns():
    _, has_header, fields = _guess(SWEDISH)

    assert has_header
    assert fields == ["date", IGNORE, "customer", "project", "hours", "comment"]


def test_english_headers_with_extras_in_them():
    _, has_header, fields = _guess(
        "Day\tClient name\tHours (h)\tDescription\n2026-03-02\tAcme\t7.5\tWorkshop\n")

    assert has_header and fields == ["date", "customer", "hours", "comment"]


def test_without_a_header_the_content_decides():
    _, has_header, fields = _guess(
        "2026-03-02\tAcme\t7,5\tWorkshop with the whole team\n"
        "2026-03-03\tBeta AB\t4\tMoving the database to the new server\n"
        "2026-03-04\tAcme\t6\tReviewing the pull requests from last week\n")

    assert not has_header
    assert fields == ["date", "customer", "hours", "comment"]


def test_two_time_of_day_columns_are_start_and_end():
    _, _, fields = _guess("Datum\tKund\tA\tB\n2026-03-02\tAcme\t08:00\t11:30\n"
                          "2026-03-03\tAcme\t09:00\t17:00\n")

    assert fields == ["date", "customer", "start", "end"]


def test_one_clock_column_alone_is_a_duration():
    _, _, fields = _guess("Datum\tKund\tX\n2026-03-02\tAcme\t7:30\n2026-03-03\tAcme\t4:15\n")

    assert fields == ["date", "customer", "hours"]


def test_repeating_short_text_is_the_project_and_varying_text_the_comment():
    _, _, fields = _guess(
        "2026-03-02\tAcme\tPlatform\tMeeting\t2\n2026-03-03\tAcme\tPlatform\tReview\t3\n"
        "2026-03-04\tAcme\tPlatform\tDev\t4\n2026-03-05\tBeta\tOps\tCall\t1\n")

    assert fields == ["date", "customer", "project", "comment", "hours"]


# ── values ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cell, hours", [
    ("7,5", Decimal("7.5")), ("7.5", Decimal("7.5")), ("7:30", Decimal("7.5")),
    ("7 h", Decimal(7)), ("7,5h", Decimal("7.5")), ("0", Decimal(0)),
    ("seven", None), ("-1", None), ("", None),
])
def test_hours_are_read_in_their_usual_forms(cell, hours):
    assert pi.parse_hours(cell) == hours


@pytest.mark.parametrize("cell, order, day", [
    ("2026-03-02", "dmy", date(2026, 3, 2)),
    ("2026-03-02 00:00:00", "dmy", date(2026, 3, 2)),
    ("2026/3/2", "dmy", date(2026, 3, 2)),
    ("02.03.2026", "dmy", date(2026, 3, 2)),
    ("2/3/26", "dmy", date(2026, 3, 2)),
    ("3/2/2026", "mdy", date(2026, 3, 2)),
    ("46083", "dmy", date(2026, 3, 2)),  # an unformatted Excel date
    ("2026-02-30", "dmy", None), ("soon", "dmy", None),
])
def test_dates_are_read_in_their_usual_forms(cell, order, day):
    assert pi.parse_date(cell, order) == day


def test_a_column_with_a_day_past_12_in_second_place_is_month_first():
    assert pi.date_order(["03/02/2026", "03/15/2026"]) == "mdy"
    assert pi.date_order(["03/02/2026", "15/03/2026"]) == "dmy"
    assert pi.date_order(["03/02/2026"]) == "dmy"  # can't tell: day first, as in Sweden


@pytest.mark.parametrize("cell, clock", [
    ("08:00", time(8)), ("8.30", time(8, 30)), ("17:45:10", time(17, 45, 10)),
    ("0,375", time(9)), ("25:00", None), ("noon", None),
])
def test_times_of_day(cell, clock):
    assert pi.parse_clock(cell) == clock


# ── rows → entries ──────────────────────────────────────────────────────────


def test_rows_become_entries_and_missing_projects_get_the_default():
    rows, has_header, fields = _guess("Datum\tKund\tTimmar\tKommentar\n"
                                      "2026-03-02\tAcme  AB\t7,5\tWorkshop\n")

    entries, problems, skipped = pi.parse(rows, has_header, fields)

    assert (problems, skipped) == ([], 0)
    assert entries == [pi.Entry(2, date(2026, 3, 2), "Acme AB", pi.DEFAULT_PROJECT,
                                Decimal("7.5"), None, None, "Workshop")]


def test_each_bad_row_says_what_to_fix_and_rows_without_time_are_skipped():
    rows, has_header, fields = _guess(
        "Datum\tKund\tTimmar\n"
        "2026-03-02\tAcme\t7\n"
        "someday\tAcme\t2\n"
        "2026-03-03\t\t2\n"
        "2026-03-04\tAcme\tlots\n"
        "2026-03-05\tAcme\t25\n"
        "2026-03-06\tAcme\t0\n"
        "2026-03-07\tAcme\t\n")

    entries, problems, skipped = pi.parse(rows, has_header, fields)

    assert [e.row for e in entries] == [2]
    assert problems == [pi.Problem(3, "“someday” is not a date"), pi.Problem(4, "No customer"),
                        pi.Problem(5, "“lots” is not a number of hours"),
                        pi.Problem(6, "25 hours is more than a day")]
    assert skipped == 2


def test_start_and_end_give_the_hours_and_must_be_in_order():
    rows = pi.read_table("Datum\tKund\tStart\tSlut\n2026-03-02\tAcme\t08:00\t11:30\n"
                         "2026-03-03\tAcme\t13:00\t12:00\n")
    has_header, fields = pi.guess_columns(rows)

    entries, problems, _ = pi.parse(rows, has_header, fields)

    assert [(e.hours, e.start, e.end) for e in entries] == [(Decimal("3.5"), time(8), time(11, 30))]
    assert problems == [pi.Problem(3, "Ends (12:00) before it starts (13:00)")]


def test_a_required_column_left_unchosen_stops_everything():
    rows = pi.read_table("Datum\tTimmar\n2026-03-02\t7\n")

    entries, problems, _ = pi.parse(rows, True, ["date", "hours"])

    assert entries == [] and problems == [pi.Problem(0, "No column chosen for: customer")]


def test_hours_only_entries_are_placed_from_eight_one_after_another():
    day = date(2026, 3, 2)
    entries = [pi.Entry(2, day, "Acme", "General", Decimal("1.5"), None, None, ""),
               pi.Entry(3, day, "Beta", "General", Decimal(2), None, None, ""),
               pi.Entry(4, day, "Acme", "General", Decimal(1), time(13), time(14), ""),
               pi.Entry(5, date(2026, 3, 3), "Acme", "General", Decimal("0.25"), None, None, "")]

    assert pi.placed(entries) == [
        (datetime(2026, 3, 2, 8), datetime(2026, 3, 2, 9, 30)),
        (datetime(2026, 3, 2, 9, 30), datetime(2026, 3, 2, 11, 30)),
        (datetime(2026, 3, 2, 13), datetime(2026, 3, 2, 14)),
        (datetime(2026, 3, 3, 8), datetime(2026, 3, 3, 8, 15)),
    ]


def test_customers_are_summed_with_their_projects():
    rows, has_header, fields = _guess(SWEDISH)
    entries, _, _ = pi.parse(rows, has_header, fields)

    assert pi.by_customer(entries) == [
        {"customer": "Acme", "entries": 2, "hours": Decimal(11), "first": date(2026, 3, 2),
         "last": date(2026, 3, 3), "projects": ["Plattform"]},
        {"customer": "Beta AB", "entries": 1, "hours": Decimal(4), "first": date(2026, 3, 3),
         "last": date(2026, 3, 3), "projects": ["Migrering"]},
    ]


def test_a_name_written_in_several_ways_takes_its_first_spelling():
    rows, has_header, fields = _guess("Datum\tKund\tProjekt\tTimmar\n"
                                      "2026-03-02\tTest Kund AB\tDrift\t1\n"
                                      "2026-03-03\ttest  kund ab\tDRIFT\t2\n"
                                      "2026-03-04\tOther\tdrift\t3\n")

    entries, _, _ = pi.parse(rows, has_header, fields)

    assert [(e.customer, e.project) for e in entries] == [
        ("Test Kund AB", "Drift"), ("Test Kund AB", "Drift"), ("Other", "drift")]
    assert [g["entries"] for g in pi.by_customer(entries)] == [2, 1]
