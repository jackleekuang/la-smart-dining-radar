"""Opening-hours logic for the dashboard, kept free of Streamlit so it can be tested.

Rows come from marts.fct_restaurant_hours: one row per open period, with day_of_week
(0 = Monday, Yelp's convention), start_time, end_time and is_overnight.
"""

from __future__ import annotations

import datetime

import pandas as pd


def _covers_same_day(start: datetime.time, end: datetime.time, overnight: bool, t: datetime.time) -> bool:
    """Does a period that starts on the selected day cover time t on that day?

    The closing minute is excluded: a place that closes at 21:00 is closed at 21:00.
    start == end means open around the clock.
    """
    if start == end:
        return True
    if overnight or end < start:
        return t >= start  # the rest of the period falls on the next day
    return start <= t < end


def _covers_after_midnight(start: datetime.time, end: datetime.time, overnight: bool, t: datetime.time) -> bool:
    """Does a period that started the previous day run past midnight and still cover t?"""
    if start == end:
        return False  # a 24-hour period is already counted for its own day
    if overnight or end < start:
        return t < end
    return False


def open_restaurant_ids(hours: pd.DataFrame, day_index: int, at_time: datetime.time) -> set[str]:
    """IDs of restaurants open on day_index (0 = Monday) at at_time.

    Two kinds of period count:
    - periods that start on the selected day and cover the time, and
    - overnight periods from the previous day that have not ended yet
      (Friday 18:00-02:00 means open at 01:00 on Saturday, not on Friday).
    """
    previous_day = (day_index - 1) % 7
    open_ids: set[str] = set()
    for row in hours.itertuples(index=False):
        overnight = bool(row.is_overnight) if pd.notna(row.is_overnight) else False
        if pd.isna(row.start_time) or pd.isna(row.end_time):
            continue
        if row.day_of_week == day_index and _covers_same_day(row.start_time, row.end_time, overnight, at_time):
            open_ids.add(row.restaurant_id)
        elif row.day_of_week == previous_day and _covers_after_midnight(row.start_time, row.end_time, overnight, at_time):
            open_ids.add(row.restaurant_id)
    return open_ids
