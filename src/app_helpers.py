"""Pure helpers for the Streamlit dashboard, kept out of app/ so they can be unit-tested."""

import datetime
import math
from zoneinfo import ZoneInfo

import pandas as pd

LA_TZ = ZoneInfo("America/Los_Angeles")
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def format_rating(rating: float | None) -> str:
    """Render a rating for display; unrated restaurants (NULL) say so instead of 'nan'."""
    if rating is None or (isinstance(rating, float) and math.isnan(rating)):
        return "Not yet rated"
    return f"⭐ {rating:g}"


def average_rating_label(ratings: pd.Series) -> str:
    """Average of rated restaurants only, or an en dash if none are rated."""
    rated = ratings.dropna()
    return f"{rated.mean():.2f}" if len(rated) else "–"


def restaurant_count_label(count: int, total: int) -> str:
    """'1 restaurant' / '12 restaurants (of 3675 total)'."""
    noun = "restaurant" if count == 1 else "restaurants"
    label = f"{count} {noun}"
    if count != total:
        label += f" (of {total} total)"
    return label


def default_open_filter(now: datetime.datetime | None = None) -> tuple[int, datetime.time]:
    """Default day index and time for the 'open at' filter: the current moment in LA.

    Args:
        now: Override for testing; any tz-aware datetime (converted to LA time).

    Returns:
        (day index into DAY_NAMES with Monday = 0, time truncated to the minute).
    """
    current = (now or datetime.datetime.now(LA_TZ)).astimezone(LA_TZ)
    return current.weekday(), current.time().replace(second=0, microsecond=0)


def table_key(ids: pd.Series, prefix: str = "restaurant_table") -> str:
    """Widget key that changes whenever the set of rows in the table changes.

    st.dataframe keeps its row selection under its key across reruns. With a fixed
    key, selecting row 1,500 and then filtering down to 20 rows left a stale
    selection pointing past the end of the table (IndexError). Keying on the rows
    shown resets the selection whenever a filter changes the table.
    """
    import hashlib

    digest = hashlib.md5("|".join(ids.astype(str)).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def valid_selection(rows: list[int] | None, n_rows: int) -> int | None:
    """First selected row position if it still exists in a table of n_rows, else None."""
    for r in rows or []:
        if 0 <= r < n_rows:
            return r
    return None
