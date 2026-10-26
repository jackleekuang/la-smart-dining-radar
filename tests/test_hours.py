"""Tests for the dashboard's open-at-time filter (app/hours.py)."""

import datetime as dt

import pandas as pd

from app.hours import open_restaurant_ids

MON, THU, FRI, SAT, SUN = 0, 3, 4, 5, 6


def _hours(*rows):
    return pd.DataFrame(rows, columns=["restaurant_id", "day_of_week", "start_time", "end_time", "is_overnight"])


T = dt.time

HOURS = _hours(
    ("lunch", FRI, T(11, 0), T(21, 0), False),
    ("late", FRI, T(18, 0), T(2, 0), True),
    ("allday", FRI, T(0, 0), T(0, 0), False),
    ("sunday_late", SUN, T(20, 0), T(1, 0), True),
)


def test_closing_minute_is_closed():
    assert "lunch" in open_restaurant_ids(HOURS, FRI, T(20, 59))
    assert "lunch" not in open_restaurant_ids(HOURS, FRI, T(21, 0))


def test_opening_minute_is_open():
    assert "lunch" in open_restaurant_ids(HOURS, FRI, T(11, 0))


def test_overnight_counts_on_the_next_day_after_midnight():
    assert "late" in open_restaurant_ids(HOURS, SAT, T(1, 0))
    assert "late" not in open_restaurant_ids(HOURS, SAT, T(2, 0))


def test_overnight_does_not_count_before_opening_on_its_own_day():
    # The old filter treated Friday 01:00 as open because 01:00 <= the 02:00 end time.
    assert "late" not in open_restaurant_ids(HOURS, FRI, T(1, 0))
    assert "late" in open_restaurant_ids(HOURS, FRI, T(23, 30))


def test_week_wraps_from_sunday_to_monday():
    assert "sunday_late" in open_restaurant_ids(HOURS, MON, T(0, 30))


def test_twenty_four_hours():
    assert "allday" in open_restaurant_ids(HOURS, FRI, T(3, 0))
    assert "allday" not in open_restaurant_ids(HOURS, SAT, T(3, 0))


def test_missing_times_are_skipped():
    bad = _hours(("x", THU, None, T(9, 0), False))
    assert open_restaurant_ids(bad, THU, T(8, 0)) == set()
