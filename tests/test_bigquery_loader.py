"""Tests for src.load.bigquery_loader._to_raw_row. No BigQuery connection required."""

import json

from src.load.bigquery_loader import _to_raw_row

# Real shape captured from a live Yelp /v3/businesses/search response during development.
SAMPLE_BUSINESS = {
    "id": "XgQ8riUvnMOBVfRG29NCEQ",
    "alias": "anju-house-los-angeles-2",
    "name": "Anju House",
    "image_url": "https://s3-media0.fl.yelpcdn.com/bphoto/UNwuQr1wKngqYHez6bhBhA/o.jpg",
    "is_closed": False,
    "url": "https://www.yelp.com/biz/anju-house-los-angeles-2",
    "review_count": 729,
    "categories": [
        {"alias": "korean", "title": "Korean"},
        {"alias": "bars", "title": "Bars"},
        {"alias": "tapasmallplates", "title": "Tapas/Small Plates"},
    ],
    "rating": 4.3,
    "coordinates": {"latitude": 34.0701519575396, "longitude": -118.3076326},
    "transactions": ["delivery", "pickup", "restaurant_reservation"],
    "price": "$$",
    "location": {
        "address1": "234 S Oxford Ave",
        "address2": "",
        "address3": None,
        "city": "Los Angeles",
        "zip_code": "90004",
        "country": "US",
        "state": "CA",
        "display_address": ["234 S Oxford Ave", "Los Angeles, CA 90004"],
    },
    "phone": "+12133155153",
    "display_phone": "(213) 315-5153",
    "distance": 1575.4777597101904,
    "business_hours": [
        {
            "open": [{"is_overnight": True, "start": "1700", "end": "0200", "day": 0}],
            "hours_type": "REGULAR",
            "is_open_now": False,
        }
    ],
}


def test_to_raw_row_maps_known_fields():
    row = _to_raw_row(SAMPLE_BUSINESS)

    assert row["id"] == "XgQ8riUvnMOBVfRG29NCEQ"
    assert row["name"] == "Anju House"
    assert row["rating"] == 4.3
    assert row["review_count"] == 729
    assert row["price"] == "$$"
    assert json.loads(row["categories"]) == SAMPLE_BUSINESS["categories"]
    assert row["latitude"] == 34.0701519575396
    assert row["longitude"] == -118.3076326
    assert row["is_closed"] is False
    assert row["address1"] == "234 S Oxford Ave"
    assert row["city"] == "Los Angeles"
    assert row["zip_code"] == "90004"
    assert row["state"] == "CA"
    assert row["country"] == "US"
    assert row["transactions"] == ["delivery", "pickup", "restaurant_reservation"]
    assert json.loads(row["business_hours"]) == SAMPLE_BUSINESS["business_hours"]
    assert row["ingestion_timestamp"]  # non-empty, set at call time


def test_to_raw_row_handles_missing_optional_fields():
    minimal_business = {"id": "abc123", "name": "No Frills Diner"}

    row = _to_raw_row(minimal_business)

    assert row["id"] == "abc123"
    assert row["latitude"] is None
    assert row["longitude"] is None
    assert row["is_closed"] is None
    assert row["address1"] is None
    assert row["city"] is None
    assert row["transactions"] == []
    assert json.loads(row["business_hours"]) == []
    assert json.loads(row["categories"]) == []
