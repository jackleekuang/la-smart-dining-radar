"""Yelp Fusion API extraction logic."""

from typing import Any

import requests

from src.config import YELP_API_KEY

YELP_API_URL = "https://api.yelp.com/v3/businesses/search"


def fetch_restaurants(
    location: str = "Los Angeles, CA",
    term: str = "restaurants",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch one page of restaurant listings from the Yelp Fusion API.

    MVP scope: a single request, no pagination or retry logic.

    Args:
        location: Free-text location query passed to Yelp.
        term: Search term/category, e.g. "restaurants".
        limit: Number of results to return (Yelp max is 50 per request).

    Returns:
        Raw list of business dicts as returned by the Yelp API.
    """
    if not YELP_API_KEY:
        raise RuntimeError("YELP_API_KEY is not set. Check your .env file.")

    headers = {"Authorization": f"Bearer {YELP_API_KEY}"}
    params = {"location": location, "term": term, "limit": limit}

    response = requests.get(YELP_API_URL, headers=headers, params=params, timeout=10)
    response.raise_for_status()

    return response.json().get("businesses", [])


if __name__ == "__main__":
    restaurants = fetch_restaurants()
    print(f"Fetched {len(restaurants)} restaurants")
    if restaurants:
        print(restaurants[0])
