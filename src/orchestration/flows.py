"""Prefect flow orchestrating extract -> load -> soda scan -> dbt run."""

import subprocess
import sys
from pathlib import Path
from typing import Any

from prefect import flow, task

from src.extract.yelp_api import fetch_restaurants
from src.load.bigquery_loader import load_restaurants

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = Path(sys.executable).parent


@task
def extract_task() -> list[dict[str, Any]]:
    """Fetch restaurant listings from the Yelp Fusion API."""
    return fetch_restaurants()


@task
def load_task(businesses: list[dict[str, Any]]) -> None:
    """Load fetched restaurant records into BigQuery's raw layer."""
    load_restaurants(businesses)


@task
def soda_scan_task() -> None:
    """Run Soda Core data quality checks against the raw layer."""
    subprocess.run(
        [
            str(VENV_BIN / "soda"),
            "scan",
            "-d", "dining_radar",
            "-c", "soda/configuration.yml",
            "soda/checks/raw_yelp_restaurants.yml",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


@task
def dbt_run_task() -> None:
    """Run dbt models to (re)build the mart layer from the raw layer."""
    subprocess.run(
        [str(VENV_BIN / "dbt"), "run", "--project-dir", "dbt_project", "--profiles-dir", "dbt_project"],
        cwd=PROJECT_ROOT,
        check=True,
    )


@flow(name="la-dining-radar-pipeline")
def dining_radar_pipeline() -> None:
    """MVP pipeline: extract -> load -> soda scan (quality gate) -> dbt run."""
    businesses = extract_task()
    load_task(businesses)
    soda_scan_task()
    dbt_run_task()


if __name__ == "__main__":
    dining_radar_pipeline()
