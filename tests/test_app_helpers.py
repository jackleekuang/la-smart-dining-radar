"""Tests for src.app_helpers. No Streamlit or BigQuery required."""

import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.app_helpers import (
    average_rating_label,
    default_open_filter,
    format_rating,
    restaurant_count_label,
)


def test_unrated_restaurant_is_labelled_not_nan() -> None:
    assert format_rating(None) == "Not yet rated"
    assert format_rating(float("nan")) == "Not yet rated"
    assert format_rating(4.5) == "⭐ 4.5"


def test_average_rating_ignores_unrated_rows() -> None:
    # Before the fix, an unrated restaurant arrived as rating 0 and pulled the
    # average down; now it is NULL and must be excluded, not counted as 0.
    assert average_rating_label(pd.Series([4.0, 5.0, None])) == "4.50"


def test_average_rating_with_no_rated_rows() -> None:
    assert average_rating_label(pd.Series([None, None], dtype="float64")) == "–"


def test_count_label_singular_and_plural() -> None:
    assert restaurant_count_label(1, 3675) == "1 restaurant (of 3675 total)"
    assert restaurant_count_label(3675, 3675) == "3675 restaurants"


def test_default_open_filter_uses_la_local_time() -> None:
    # 2026-10-28 03:15 UTC is Tuesday 2026-10-27 20:15 in Los Angeles (PDT).
    utc = datetime.datetime(2026, 10, 28, 3, 15, 42, tzinfo=ZoneInfo("UTC"))
    day, time = default_open_filter(utc)
    assert day == 1  # Tuesday
    assert time == datetime.time(20, 15)


def test_table_key_changes_with_rows_and_is_stable() -> None:
    from src.app_helpers import table_key

    all_rows = pd.Series(["a", "b", "c"])
    assert table_key(all_rows) == table_key(pd.Series(["a", "b", "c"]))
    assert table_key(all_rows) != table_key(pd.Series(["a"]))


def test_valid_selection_drops_rows_past_the_end() -> None:
    from src.app_helpers import valid_selection

    assert valid_selection([1500], 20) is None  # stale selection after filtering
    assert valid_selection([3], 20) == 3
    assert valid_selection([], 20) is None
    assert valid_selection(None, 20) is None
