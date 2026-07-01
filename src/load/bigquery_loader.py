"""BigQuery write/load logic for the raw layer."""

import json
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery
from google.oauth2 import service_account

from src.config import BQ_DATASET_RAW, GCP_CREDENTIALS_PATH, GCP_PROJECT_ID

RAW_TABLE_ID = "raw_yelp_restaurants"


def get_bigquery_client() -> bigquery.Client:
    """Build a BigQuery client authenticated with the configured service account."""
    credentials = service_account.Credentials.from_service_account_file(GCP_CREDENTIALS_PATH)
    return bigquery.Client(project=GCP_PROJECT_ID, credentials=credentials)


def _to_raw_row(business: dict[str, Any]) -> dict[str, Any]:
    """Map a raw Yelp business dict to the raw_yelp_restaurants schema."""
    coordinates = business.get("coordinates") or {}
    return {
        "id": business.get("id"),
        "name": business.get("name"),
        "rating": business.get("rating"),
        "review_count": business.get("review_count"),
        "price": business.get("price"),
        "categories": json.dumps(business.get("categories", [])),
        "latitude": coordinates.get("latitude"),
        "longitude": coordinates.get("longitude"),
        "ingestion_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def load_restaurants(businesses: list[dict[str, Any]]) -> None:
    """Insert raw Yelp business records into raw_yelp_restaurants.

    MVP scope: direct streaming insert (append-only), no upsert/dedup.

    Args:
        businesses: Raw business dicts as returned by fetch_restaurants().
    """
    client = get_bigquery_client()
    table_ref = f"{GCP_PROJECT_ID}.{BQ_DATASET_RAW}.{RAW_TABLE_ID}"
    rows = [_to_raw_row(business) for business in businesses]

    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        raise RuntimeError(f"Failed to insert rows into {table_ref}: {errors}")


if __name__ == "__main__":
    from src.extract.yelp_api import fetch_restaurants

    fetched = fetch_restaurants()
    load_restaurants(fetched)
    print(f"Loaded {len(fetched)} restaurants into {BQ_DATASET_RAW}.{RAW_TABLE_ID}")
