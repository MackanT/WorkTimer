"""Tests for the Reports page pure logic (rounding + date maths)."""

from datetime import date

from src.pages.reports import (
    _count_workdays,
    _pct_change,
    _period_bounds,
    _prev_range,
    compute_report_rows,
    round_hours,
)


def test_round_hours_nearest():
    assert round_hours(2.4, 15, "nearest") == 2.5   # 2.4h -> nearest 0.25h
    assert round_hours(2.1, 15, "nearest") == 2.0
    assert round_hours(1.0, 30, "nearest") == 1.0


def test_round_hours_up_and_down():
    assert round_hours(2.01, 15, "up") == 2.25
    assert round_hours(2.49, 15, "down") == 2.25
    assert round_hours(0.02, 6, "up") == 0.1        # any work -> at least 6 min


def test_round_hours_off_or_zero_is_identity():
    assert round_hours(2.4, 0) == 2.4
    assert round_hours(0, 15) == 0


def test_compute_report_rows_scales_amount_by_rounding():
    raw = [{"project": "Site", "hours": 2.4, "cost": 240.0}]  # 100/h
    rows = compute_report_rows(raw, 15, "nearest")
    assert rows[0]["hours"] == 2.5
    assert abs(rows[0]["amount"] - 250.0) < 1e-6           # 2.5 * 100
    assert rows[0]["raw_hours"] == 2.4


def test_compute_report_rows_no_rounding_preserves_totals():
    raw = [{"project": "A", "hours": 1.37, "cost": 137.0}]
    rows = compute_report_rows(raw, 0)
    assert rows[0]["hours"] == 1.37
    assert abs(rows[0]["amount"] - 137.0) < 1e-6


def test_compute_report_rows_handles_zero_hours():
    rows = compute_report_rows([{"project": "X", "hours": 0, "cost": 0}], 15)
    assert rows[0]["hours"] == 0
    assert rows[0]["amount"] == 0


def test_prev_range_is_equal_length_and_adjacent():
    assert _prev_range("2026-08-01", "2026-08-31") == ("2026-07-01", "2026-07-31")
    assert _prev_range("2026-08-10", "2026-08-16") == ("2026-08-03", "2026-08-09")
    assert _prev_range("2026-08-05", "2026-08-05") == ("2026-08-04", "2026-08-04")
    assert _prev_range("bad", "x") == (None, None)


def test_count_workdays():
    # Aug 2026 starts on a Saturday -> 21 weekdays.
    assert _count_workdays("2026-08-01", "2026-08-31") == 21
    assert _count_workdays("2026-08-01", "2026-08-02") == 0   # Sat + Sun
    assert _count_workdays("2026-08-03", "2026-08-07") == 5   # Mon–Fri
    assert _count_workdays("bad", "x") == 0


def test_pct_change():
    assert _pct_change(110, 100) == 10.0
    assert _pct_change(80, 100) == -20.0
    assert _pct_change(5, 0) is None


def test_period_bounds_month_is_mtd_vs_prev_month_same_span():
    cs, ce, ps, pe = _period_bounds("Month", "", "", date(2026, 8, 7))
    assert (cs, ce) == ("2026-08-01", "2026-08-07")   # month-to-date
    assert (ps, pe) == ("2026-07-01", "2026-07-07")   # prev month, same span


def test_period_bounds_month_clamps_to_short_prev_month():
    cs, ce, ps, pe = _period_bounds("Month", "", "", date(2026, 3, 31))
    assert (cs, ce) == ("2026-03-01", "2026-03-31")
    assert (ps, pe) == ("2026-02-01", "2026-02-28")   # Feb has no 31st


def test_period_bounds_week_is_week_to_date():
    cs, ce, ps, pe = _period_bounds("Week", "", "", date(2026, 8, 5))  # Wed
    assert (cs, ce) == ("2026-08-03", "2026-08-05")   # Mon → today
    assert (ps, pe) == ("2026-07-27", "2026-07-29")   # same span, prev week


def test_period_bounds_custom_uses_preceding_equal_length():
    cs, ce, ps, pe = _period_bounds("Custom", "2026-08-01", "2026-08-10", date(2026, 8, 20))
    assert (cs, ce) == ("2026-08-01", "2026-08-10")
    assert (ps, pe) == _prev_range("2026-08-01", "2026-08-10")
