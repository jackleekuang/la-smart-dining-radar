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


def _seconds_since_midnight(times: pd.Series) -> pd.Series:
    """Convert a column of TIME values (datetime.time objects, as BigQuery returns them) to seconds."""
    return pd.Series(
        [t.hour * 3600 + t.minute * 60 + t.second for t in times], index=times.index, dtype="int64"
    )


def open_restaurant_ids(hours: pd.DataFrame, day_of_week: int, at_time: datetime.time) -> set[str]:
    """IDs of restaurants open at (day_of_week, at_time), vectorized over fct_restaurant_hours.

    Overnight periods are stored on the day they start (e.g. Mon 17:00-02:00 has
    day_of_week = 0), so a restaurant is open on day D at time T if any of:
      * a same-day period on D covers T (start <= T <= end);
      * an overnight period starting on D has started (T >= start);
      * an overnight period that started the previous day hasn't ended yet (T <= end).

    Args:
        hours: fct_restaurant_hours rows (restaurant_id, day_of_week, start_time,
            end_time, is_overnight).
        day_of_week: 0 = Monday ... 6 = Sunday.
        at_time: Local time to test.
    """
    previous_day = (day_of_week - 1) % 7
    hours = hours[hours["day_of_week"].isin([day_of_week, previous_day])]
    if hours.empty:
        return set()
    t = at_time.hour * 3600 + at_time.minute * 60 + at_time.second
    start = _seconds_since_midnight(hours["start_time"])
    end = _seconds_since_midnight(hours["end_time"])
    overnight = hours["is_overnight"].fillna(False).astype(bool)
    day = hours["day_of_week"]

    same_day = (day == day_of_week) & ~overnight & (start <= t) & (t <= end)
    started_tonight = (day == day_of_week) & overnight & (t >= start)
    carried_over = (day == previous_day) & overnight & (t <= end)
    return set(hours.loc[same_day | started_tonight | carried_over, "restaurant_id"])


def map_points(restaurants: pd.DataFrame) -> list[list]:
    """Rows for folium.FastMarkerCluster: [lat, lng, popup_html, tooltip].

    Names and addresses are HTML-escaped because they are vendor-supplied text
    rendered inside a popup.
    """
    from html import escape

    points: list[list] = []
    cols = ["latitude", "longitude", "name", "rating", "review_count", "price", "address1", "city"]
    for lat, lng, name, rating, reviews, price, address, city in restaurants[cols].itertuples(index=False):
        if pd.isna(lat) or pd.isna(lng):
            continue
        reviews_text = "" if pd.isna(reviews) else f" ({int(reviews)} reviews)"
        popup = (
            f"<b>{escape(str(name))}</b><br>"
            f"{format_rating(rating)}{reviews_text}<br>"
            f"{escape(str(price))}<br>"
            f"{escape(str(address))}, {escape(str(city))}"
        )
        points.append([float(lat), float(lng), popup, str(name)])
    return points
