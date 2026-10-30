"""Static settings for the v2 pipeline. Values that differ per environment come from env vars."""

import os

# City of Los Angeles bounding box (lon/lat). Deliberately a little wider than the city
# limits; precise geography is applied downstream in dbt, not at extraction.
LA_BBOX = {"xmin": -118.67, "ymin": 33.70, "xmax": -118.15, "ymax": 34.34}

# Overture Maps Places mirror maintained by CARTO in BigQuery public data. It only ever holds
# the latest release, which is why the pipeline snapshots it into our own raw table.
OVERTURE_PLACES_TABLE = os.getenv("OVERTURE_PLACES_TABLE", "bigquery-public-data.overture_maps.place")

# Coarse, schema-agnostic food filter applied to the raw JSON at extraction to keep storage
# small. The precise category filter lives in dbt (macro is_food_category).
OVERTURE_FOOD_REGEX = (
    r"restaurant|cafe|coffee|bakery|\bbar\b|_bar\b|\bpub\b|brewery|food_truck|diner|bistro|"
    r"eatery|tea_room|dessert|ice_cream|juice|\bdeli\b|pizza|taco|sushi|ramen|noodle|bbq|barbecue"
)

# Safety valve: the monthly Overture snapshot scans the public table. Fail before running a
# query whose dry-run estimate exceeds this many bytes (BigQuery free tier is 1 TiB/month).
OVERTURE_MAX_BYTES_BILLED = int(os.getenv("OVERTURE_MAX_BYTES_BILLED", str(200 * 1024**3)))

# LA City Office of Finance "Listing of All Businesses" (Socrata dataset r4uk-afju).
LA_CITY_DATASET_URL = os.getenv(
    "LA_CITY_DATASET_URL", "https://data.lacity.org/resource/r4uk-afju.json"
)
LA_CITY_NAICS_FIELD = os.getenv("LA_CITY_NAICS_FIELD", "naics")
LA_CITY_NAICS_PREFIX = "722"  # NAICS 722 = Food Services and Drinking Places
SOCRATA_APP_TOKEN = os.getenv("SOCRATA_APP_TOKEN", "")
SOCRATA_PAGE_SIZE = 50_000

# Raw tables (dataset = BQ_DATASET_RAW).
RAW_OVERTURE_TABLE = "raw_overture_places"
RAW_LA_CITY_TABLE = "raw_la_city_businesses"
