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


def map_points(restaurants: pd.DataFrame) -> list[list]:
    """Rows for folium.FastMarkerCluster: [lat, lng, popup_html, tooltip].

    Name, price and address are HTML-escaped (popup and tooltip) because they are
    vendor-supplied text that Leaflet renders as HTML.
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
        points.append([float(lat), float(lng), popup, escape(str(name))])
    return points
