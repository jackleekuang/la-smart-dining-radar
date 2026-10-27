"""Tests for the vectorized open-hours filter and map point builder in src.app_helpers."""

import datetime

import pandas as pd

from src.app_helpers import map_points, open_restaurant_ids

T = datetime.time
MON, TUE, SUN = 0, 1, 6

HOURS = pd.DataFrame(
    [
        # lunch spot, Mon 11:00-15:00
        {"restaurant_id": "lunch", "day_of_week": MON, "start_time": T(11, 0), "end_time": T(15, 0), "is_overnight": False},
        # bar, Mon 17:00 -> Tue 02:00 (stored on Monday)
        {"restaurant_id": "bar", "day_of_week": MON, "start_time": T(17, 0), "end_time": T(2, 0), "is_overnight": True},
        # late diner, Sun 20:00 -> Mon 03:00 (stored on Sunday)
        {"restaurant_id": "diner", "day_of_week": SUN, "start_time": T(20, 0), "end_time": T(3, 0), "is_overnight": True},
    ]
)


def test_same_day_period() -> None:
    assert open_restaurant_ids(HOURS, MON, T(12, 30)) == {"lunch"}
    assert open_restaurant_ids(HOURS, MON, T(16, 0)) == set()


def test_overnight_period_after_it_starts() -> None:
    assert open_restaurant_ids(HOURS, MON, T(23, 0)) == {"bar"}


def test_overnight_period_carries_into_next_day() -> None:
    # Tue 01:00 is still Monday night for the bar.
    assert open_restaurant_ids(HOURS, TUE, T(1, 0)) == {"bar"}


def test_early_morning_belongs_to_previous_night_not_today() -> None:
    # Regression: the old row-wise check said the bar was open Mon 01:00
    # (01:00 <= 02:00 on Monday's own row). Mon 01:00 is actually Sunday night,
    # when only the diner is open.
    assert open_restaurant_ids(HOURS, MON, T(1, 0)) == {"diner"}


def test_week_wraps_from_sunday_to_monday() -> None:
    assert "diner" in open_restaurant_ids(HOURS, MON, T(2, 30))
    assert "diner" not in open_restaurant_ids(HOURS, MON, T(3, 30))


def test_empty_hours() -> None:
    assert open_restaurant_ids(HOURS.iloc[0:0], MON, T(12, 0)) == set()


def test_map_points_escape_vendor_text_and_skip_missing_coordinates() -> None:
    restaurants = pd.DataFrame(
        [
            {"latitude": 34.05, "longitude": -118.25, "name": "<script>x</script>", "rating": None,
             "review_count": 0, "price": "$$", "address1": "1 Main St", "city": "Los Angeles"},
            {"latitude": None, "longitude": -118.25, "name": "No coords", "rating": 4.5,
             "review_count": 10, "price": "$", "address1": "2 Main St", "city": "Los Angeles"},
        ]
    )
    points = map_points(restaurants)
    assert len(points) == 1
    lat, lng, popup, tooltip = points[0]
    assert (lat, lng) == (34.05, -118.25)
    assert "<script>" not in popup and "&lt;script&gt;" in popup
    assert "Not yet rated" in popup
