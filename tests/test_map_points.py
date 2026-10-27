"""Tests for src.app_helpers.map_points (FastMarkerCluster input)."""

import pandas as pd

from src.app_helpers import map_points


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
    assert tooltip == "&lt;script&gt;x&lt;/script&gt;"  # Leaflet renders tooltip strings as HTML


def test_map_points_formats_rated_restaurant() -> None:
    restaurants = pd.DataFrame(
        [{"latitude": 34.0, "longitude": -118.3, "name": "Bestia", "rating": 4.3,
          "review_count": 8415, "price": "$$$", "address1": "2121 E 7th Pl", "city": "Los Angeles"}]
    )
    (_, _, popup, _), = map_points(restaurants)
    assert "⭐ 4.3 (8415 reviews)" in popup
