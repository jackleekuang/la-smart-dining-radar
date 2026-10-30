"""BigQuery helpers for the v2 pipeline: raw-table DDL, batch loads, and cost-guarded queries."""

from __future__ import annotations

import datetime as dt
from typing import Any

from google.cloud import bigquery

from src.config import BQ_DATASET_RAW, GCP_PROJECT_ID
from src.load.bigquery_loader import get_bigquery_client
from src.v2 import settings

OVERTURE_SCHEMA = [
    bigquery.SchemaField("place_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("lon", "FLOAT64"),
    bigquery.SchemaField("lat", "FLOAT64"),
    bigquery.SchemaField("payload", "STRING", mode="REQUIRED", description="Full Overture row as JSON"),
    bigquery.SchemaField("snapshot_release", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("snapshot_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("_loaded_at", "TIMESTAMP", mode="REQUIRED"),
]

LA_CITY_SCHEMA = [
    bigquery.SchemaField("source_row_id", "STRING"),
    bigquery.SchemaField("source_updated_at", "TIMESTAMP"),
    bigquery.SchemaField("payload", "STRING", mode="REQUIRED", description="Full Socrata row as JSON"),
    bigquery.SchemaField("_loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def table_id(name: str) -> str:
    """Fully qualified id for a table in the raw dataset."""
    return f"{GCP_PROJECT_ID}.{BQ_DATASET_RAW}.{name}"


def ensure_raw_tables(client: bigquery.Client | None = None) -> None:
    """Create the two raw tables if missing: partitioned by load/snapshot date to bound scans."""
    client = client or get_bigquery_client()

    overture = bigquery.Table(table_id(settings.RAW_OVERTURE_TABLE), schema=OVERTURE_SCHEMA)
    overture.time_partitioning = bigquery.TimePartitioning(field="snapshot_date")
    overture.clustering_fields = ["place_id"]
    client.create_table(overture, exists_ok=True)

    la_city = bigquery.Table(table_id(settings.RAW_LA_CITY_TABLE), schema=LA_CITY_SCHEMA)
    la_city.time_partitioning = bigquery.TimePartitioning(field="_loaded_at")
    client.create_table(la_city, exists_ok=True)


def run_query(
    sql: str,
    params: list[bigquery.ScalarQueryParameter] | None = None,
    max_bytes_billed: int | None = None,
    client: bigquery.Client | None = None,
) -> tuple[bigquery.table.RowIterator, int]:
    """Dry-run first; refuse to run if the estimate exceeds ``max_bytes_billed``.

    Returns the result rows and the estimated bytes processed. ``maximum_bytes_billed`` is also
    set on the real job, so BigQuery itself enforces the ceiling even if the estimate was off.
    """
    client = client or get_bigquery_client()
    dry = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(query_parameters=params or [], dry_run=True, use_query_cache=False),
    )
    estimate = int(dry.total_bytes_processed or 0)
    if max_bytes_billed is not None and estimate > max_bytes_billed:
        raise RuntimeError(
            f"Query would scan {estimate / 1024**3:.1f} GiB, above the {max_bytes_billed / 1024**3:.1f} GiB guard."
        )
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(query_parameters=params or [], maximum_bytes_billed=max_bytes_billed),
    )
    return job.result(), estimate


def load_rows(table_name: str, rows: list[dict[str, Any]], schema: list[bigquery.SchemaField]) -> int:
    """Append rows with a batch load job (free, no streaming buffer, no 10 MB request cap)."""
    if not rows:
        return 0
    client = get_bigquery_client()
    job = client.load_table_from_json(
        rows,
        table_id(table_name),
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ),
    )
    job.result()
    return len(rows)


def max_timestamp(table_name: str, column: str) -> str | None:
    """Watermark for incremental loads: latest value already landed, as an ISO string."""
    client = get_bigquery_client()
    rows = client.query(f"SELECT MAX({column}) AS wm FROM `{table_id(table_name)}`").result()
    value = next(iter(rows)).wm
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None).isoformat(timespec="seconds")
    return str(value)
