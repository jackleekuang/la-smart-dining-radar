"""DineRadar 2.0 Prefect flow: two open sources → BigQuery raw → Soda gate → dbt build.

Why an orchestrator is needed here (and wasn't, really, in v1):
- two sources with different behaviour (a public BigQuery table that only keeps the latest
  Overture release, and a mutable Socrata API that needs a watermark);
- task-level retries for the flaky HTTP source, without re-running the expensive snapshot;
- idempotent, parameterised reruns (force a release reload, or a full LA City reload);
- one schedule and one run history for the whole chain.

Run once:   python -m src.orchestration.flows_v2
Schedule:   python -m src.orchestration.flows_v2 --serve   (monthly, Prefect 3 `serve`)
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

# Prefect's managed pool loads this file by path from a fresh git clone; make the
# project root importable so `from src...` works there as it does locally.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import requests
from google.cloud import bigquery
from prefect import flow, get_run_logger, task

from src.orchestration.runtime_env import ensure_distutils, materialize_gcp_credentials
from src.observability.run_log import record_dbt_results, record_soda_results, track_step
from src.v2 import bq, settings, socrata
from src.v2.overture_sql import (
    build_release_count_sql,
    build_release_delete_sql,
    build_snapshot_insert,
    detect_release,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = PROJECT_ROOT / "dbt_project"
SODA_DIR = PROJECT_ROOT / "soda"
FLOW_NAME = "dineradar-v2-landscape"


@task(retries=2, retry_delay_seconds=30)
def snapshot_overture(force: bool = False) -> dict:
    """Copy the current Overture release (LA, food-related) into raw, once per release."""
    with track_step(FLOW_NAME, "snapshot_overture") as step:
        result = _snapshot_overture(force)
        step.rows_processed = result["rows"]
        step.detail = f"release {result['release']}" + (" (already loaded, skipped)" if result["skipped"] else "")
    return result


def _snapshot_overture(force: bool) -> dict:
    logger = get_run_logger()
    client = bq.get_bigquery_client()
    bq.ensure_raw_tables(client)

    source = client.get_table(settings.OVERTURE_PLACES_TABLE)
    release = detect_release(source.labels, source.modified)
    params = [
        bigquery.ScalarQueryParameter("snapshot_release", "STRING", release),
        bigquery.ScalarQueryParameter("snapshot_date", "DATE", source.modified.date()),
    ]
    target = bq.table_id(settings.RAW_OVERTURE_TABLE)

    existing = next(iter(client.query(build_release_count_sql(target), job_config=bigquery.QueryJobConfig(
        query_parameters=params[:1])).result())).n
    if existing and not force:
        logger.info("Overture release %s already loaded (%s rows) — skipping.", release, existing)
        return {"release": release, "rows": existing, "skipped": True}
    if existing and force:
        client.query(build_release_delete_sql(target), job_config=bigquery.QueryJobConfig(
            query_parameters=params[:1])).result()
        logger.info("Deleted %s rows of release %s before forced reload.", existing, release)

    sql = build_snapshot_insert(target, settings.OVERTURE_PLACES_TABLE, settings.LA_BBOX, settings.OVERTURE_FOOD_REGEX)
    _, estimate = bq.run_query(sql, params, settings.OVERTURE_MAX_BYTES_BILLED, client)
    loaded = next(iter(client.query(build_release_count_sql(target), job_config=bigquery.QueryJobConfig(
        query_parameters=params[:1])).result())).n
    logger.info("Loaded %s rows for Overture release %s (scanned ~%.1f GiB).", loaded, release, estimate / 1024**3)
    return {"release": release, "rows": loaded, "skipped": False}


def _fetch_page(url: str, params: dict[str, str], headers: dict[str, str]) -> list[dict]:
    response = requests.get(url, params=params, headers=headers, timeout=60)
    response.raise_for_status()
    return response.json()


@task(retries=3, retry_delay_seconds=[10, 60, 180])
def extract_load_la_city(full_refresh: bool = False) -> int:
    """Pull LA City food-service businesses changed since the last load, append to raw."""
    with track_step(FLOW_NAME, "extract_load_la_city") as step:
        step.rows_processed = _extract_load_la_city(full_refresh)
    return step.rows_processed


def _extract_load_la_city(full_refresh: bool) -> int:
    logger = get_run_logger()
    bq.ensure_raw_tables()
    watermark = None if full_refresh else bq.max_timestamp(settings.RAW_LA_CITY_TABLE, "source_updated_at")
    logger.info("LA City watermark: %s", watermark or "none (full load)")

    headers = {"X-App-Token": settings.SOCRATA_APP_TOKEN} if settings.SOCRATA_APP_TOKEN else {}
    loaded_at = dt.datetime.now(dt.timezone.utc).isoformat()
    total = 0
    for page in socrata.iter_pages(
        _fetch_page,
        settings.LA_CITY_DATASET_URL,
        settings.LA_CITY_NAICS_FIELD,
        settings.LA_CITY_NAICS_PREFIX,
        watermark,
        settings.SOCRATA_PAGE_SIZE,
        headers,
    ):
        total += bq.load_rows(settings.RAW_LA_CITY_TABLE, socrata.to_raw_rows(page, loaded_at), bq.LA_CITY_SCHEMA)
    logger.info("Appended %s LA City rows.", total)
    return total


@task
def soda_gate(checks_files: list[str]) -> None:
    """Fail the run before dbt if the raw layer breaks its contract (schema, freshness, volume)."""
    # Everything inside track_step, so a failure while importing or configuring Soda is
    # recorded as a failed step (it was not on 2026-10-30, when the distutils import failed).
    with track_step(FLOW_NAME, "soda_gate") as step:
        ensure_distutils()
        from soda.scan import Scan

        scan = Scan()
        scan.set_data_source_name("dining_radar")
        scan.add_configuration_yaml_file(str(SODA_DIR / "configuration.yml"))
        for name in checks_files:
            scan.add_sodacl_yaml_file(str(SODA_DIR / "checks" / name))
        scan.execute()
        get_run_logger().info(scan.get_logs_text())
        step.detail = record_soda_results(FLOW_NAME, scan.get_scan_results())
        if getattr(scan, "has_check_warns", lambda: False)() and not scan.has_check_fails():
            step.status = "warned"
        scan.assert_no_checks_fail()


@task
def dbt_build(select: str = "tag:v2") -> None:
    """Seeds, snapshots, models and tests for the v2 DAG, in dependency order."""
    from dbt.cli.main import dbtRunner

    with track_step(FLOW_NAME, "dbt_build") as step:
        result = dbtRunner().invoke(
            ["build", "--select", select, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
        )
        step.detail = record_dbt_results(FLOW_NAME, DBT_DIR / "target" / "run_results.json")
        if not result.success:
            raise RuntimeError(f"dbt build failed for selector {select!r}: {step.detail}")
        if " warn" in step.detail:
            step.status = "warned"


@flow(name="dineradar-v2-landscape")
def dineradar_v2(force_overture: bool = False, full_refresh_la_city: bool = False) -> dict:
    """Snapshot Overture + incrementally load LA City → Soda gate → dbt build."""
    materialize_gcp_credentials()
    overture = snapshot_overture(force_overture)
    la_rows = extract_load_la_city(full_refresh_la_city)
    soda_gate(["v2_raw_overture_places.yml", "v2_raw_la_city_businesses.yml"])
    dbt_build("tag:v2")
    return {"overture": overture, "la_city_rows": la_rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help="Run as a long-lived scheduled deployment.")
    parser.add_argument("--force-overture", action="store_true")
    parser.add_argument("--full-refresh-la-city", action="store_true")
    args = parser.parse_args()
    if args.serve:
        # Overture publishes monthly; CARTO syncs a few days later. Run on the 8th at 09:00.
        dineradar_v2.serve(name="monthly", cron="0 9 8 * *")
    else:
        dineradar_v2(args.force_overture, args.full_refresh_la_city)
