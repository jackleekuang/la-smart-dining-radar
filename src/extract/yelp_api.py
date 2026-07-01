"""Yelp Fusion API extraction logic."""

import math
import time
from typing import Any

import requests

from src.config import YELP_API_KEY

YELP_API_URL = "https://api.yelp.com/v3/businesses/search"
MAX_OFFSET = 950  # Yelp hard cap: offset + limit <= 1000 per query
PAGE_SIZE = 50
REQUEST_DELAY_SECONDS = 0.2
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0

# Curated LA food neighborhoods (name, latitude, longitude), grounded in local
# food-media neighborhood guides rather than a blind geographic grid — see
# project plan for sources. Two clusters: west/central LA and the Eastside.
CORE_NEIGHBORHOODS: list[tuple[str, float, float]] = [
    ("Downtown LA", 34.0407, -118.2468),
    ("Koreatown", 34.0616, -118.3000),
    ("Hollywood", 34.1016, -118.3269),
    ("West Hollywood", 34.0900, -118.3617),
    ("Beverly Hills", 34.0736, -118.4004),
    ("Silver Lake", 34.0869, -118.2702),
    ("Echo Park", 34.0782, -118.2606),
    ("Los Feliz", 34.1073, -118.2903),
    ("Thai Town / East Hollywood", 34.0975, -118.3009),
    ("Highland Park", 34.1101, -118.1937),
]
NEIGHBORHOOD_RADIUS_M = 3000


def _search(
    latitude: float,
    longitude: float,
    radius: int,
    term: str = "restaurants",
    limit: int = PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch one page of restaurant listings around a geo point from the Yelp Fusion API.

    Args:
        latitude: Search center latitude.
        longitude: Search center longitude.
        radius: Search radius in meters (Yelp max is 40000).
        term: Search term/category, e.g. "restaurants".
        limit: Number of results to return (Yelp max is 50 per request).
        offset: Pagination offset (Yelp caps offset + limit at 1000).

    Retries on HTTP 429 (rate limited) with linear backoff, since bursts of
    calls across many geo points can trigger Yelp's per-second throttling
    independently of the daily quota or per-query offset cap.

    Returns:
        Raw list of business dicts as returned by the Yelp API.
    """
    if not YELP_API_KEY:
        raise RuntimeError("YELP_API_KEY is not set. Check your .env file.")

    headers = {"Authorization": f"Bearer {YELP_API_KEY}"}
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "radius": radius,
        "term": term,
        "limit": limit,
        "offset": offset,
    }

    for attempt in range(MAX_RETRIES):
        response = requests.get(YELP_API_URL, headers=headers, params=params, timeout=10)
        if response.status_code == 429 and attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json().get("businesses", [])

    return []  # unreachable: last attempt either returns or raises via raise_for_status


def fetch_cell(
    latitude: float,
    longitude: float,
    radius: int,
    term: str = "restaurants",
    max_offset: int = MAX_OFFSET,
) -> tuple[list[dict[str, Any]], int | None]:
    """Paginate a single geo point until exhausted or the account's offset cap.

    Args:
        latitude: Search center latitude.
        longitude: Search center longitude.
        radius: Search radius in meters.
        term: Search term/category, e.g. "restaurants".
        max_offset: Stop paginating past this offset (skips a known-doomed call).

    Returns:
        A tuple of (business dicts collected across all pages, discovered offset
        cap if this account's real ceiling was hit, else None).
    """
    results: list[dict[str, Any]] = []
    offset = 0
    discovered_cap: int | None = None

    while offset <= max_offset:
        try:
            page = _search(latitude, longitude, radius, term=term, offset=offset)
        except requests.exceptions.HTTPError as exc:
            time.sleep(REQUEST_DELAY_SECONDS)
            if exc.response is not None and exc.response.status_code == 400:
                # Yelp caps offset + limit per account tier; remember the last
                # offset that actually worked so later cells skip the probe.
                discovered_cap = offset - PAGE_SIZE
                break
            raise
        # Pace every call uniformly (not just successful ones) so back-to-back
        # cells never fire requests with zero gap between them.
        time.sleep(REQUEST_DELAY_SECONDS)
        if not page:
            break
        results.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return results, discovered_cap


def _subdivide(
    center_lat: float, center_lng: float, radius_m: int,
) -> list[tuple[float, float, int]]:
    """Split one coarse point into a 2x2 grid of smaller, less-overlapping sub-points.

    Yelp's per-query offset+limit cap means a single large-radius query over a
    dense area only ever surfaces a small slice of what's really there. Covering
    the same footprint with several smaller-radius points gives each its own
    independent cap budget, without expanding the geographic area searched.
    """
    sub_radius = radius_m // 2
    offset_lat = sub_radius / 111_000
    offset_lng = sub_radius / (111_000 * math.cos(math.radians(center_lat)))
    return [
        (center_lat + offset_lat, center_lng + offset_lng, sub_radius),
        (center_lat + offset_lat, center_lng - offset_lng, sub_radius),
        (center_lat - offset_lat, center_lng + offset_lng, sub_radius),
        (center_lat - offset_lat, center_lng - offset_lng, sub_radius),
    ]


def fetch_all_restaurants(term: str = "restaurants") -> list[dict[str, Any]]:
    """Fetch restaurants across all curated LA neighborhoods.

    Each neighborhood is subdivided into 4 smaller-radius sub-points (see
    _subdivide) to get more independent offset-cap budgets out of the same
    footprint. Sub-points and neighborhoods overlap geographically by design;
    duplicate businesses are expected and deduplicated downstream by the dbt
    staging model, not here.

    Args:
        term: Search term/category, e.g. "restaurants".

    Returns:
        Combined (not deduplicated) list of business dicts across all neighborhoods.
    """
    query_points = [
        point
        for _name, lat, lng in CORE_NEIGHBORHOODS
        for point in _subdivide(lat, lng, NEIGHBORHOOD_RADIUS_M)
    ]

    all_results: list[dict[str, Any]] = []
    known_max_offset = MAX_OFFSET
    for latitude, longitude, radius in query_points:
        results, discovered_cap = fetch_cell(
            latitude, longitude, radius, term=term, max_offset=known_max_offset
        )
        all_results.extend(results)
        if discovered_cap is not None:
            known_max_offset = min(known_max_offset, discovered_cap)
    return all_results


if __name__ == "__main__":
    restaurants = fetch_all_restaurants()
    distinct_ids = {r["id"] for r in restaurants}
    print(f"Fetched {len(restaurants)} listings, {len(distinct_ids)} distinct restaurants")
    if restaurants:
        print(restaurants[0])
