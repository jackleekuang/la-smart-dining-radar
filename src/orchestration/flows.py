"""Prefect flow orchestrating extract -> load -> soda scan -> dbt run."""

import subprocess
import sys
from pathlib import Path
from typing import Any

from prefect import flow, get_run_logger, task

from src.extract.yelp_api import fetch_all_restaurants
from src.load.bigquery_loader import load_restaurants
from src.orchestration.soda_exit import SodaOutcome, interpret_soda_exit_code

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = Path(sys.executable).parent


@task
def extract_task() -> list[dict[str, Any]]:
    """Fetch restaurant listings from the Yelp Fusion API across all core neighborhoods."""
    return fetch_all_restaurants()


@task
def load_task(businesses: list[dict[str, Any]]) -> None:
    """Load fetched restaurant records into BigQuery's raw layer."""
    load_restaurants(businesses)


@task
def soda_scan_task() -> None:
    """Run Soda Core data quality checks against the raw layer.

    Warn-level checks (e.g. a few out-of-area records, slightly stale data) are
    logged and the run continues; fail-level checks or scan errors stop it.
    """
    result = subprocess.run(
        [
            str(VENV_BIN / "soda"),
            "scan",
            "-d", "dining_radar",
            "-c", "soda/configuration.yml",
            "soda/checks/raw_yelp_restaurants.yml",
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )
    outcome = interpret_soda_exit_code(result.returncode)
    if outcome is SodaOutcome.WARNED:
        get_run_logger().warning("Soda raw-layer scan passed with warnings; see scan output above.")
    elif outcome is SodaOutcome.FAILED:
        raise RuntimeError(f"Soda raw-layer scan failed (exit code {result.returncode}).")


@task
def dbt_seed_task() -> None:
    """Load dbt seeds (e.g. the city alias/reference lookups) into BigQuery."""
    subprocess.run(
        [str(VENV_BIN / "dbt"), "seed", "--project-dir", "dbt_project", "--profiles-dir", "dbt_project"],
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


@task
def dbt_test_task() -> None:
    """Run dbt tests to validate the mart layer after a rebuild.

    Failures here (e.g. an unrecognized city value) are the pipeline's main
    quality gate against the mart layer -- distinct from soda_scan_task, which
    only guards the raw layer before any transformation runs.
    """
    subprocess.run(
        [str(VENV_BIN / "dbt"), "test", "--project-dir", "dbt_project", "--profiles-dir", "dbt_project"],
        cwd=PROJECT_ROOT,
        check=True,
    )


@flow(name="la-dining-radar-pipeline")
def dining_radar_pipeline() -> None:
    """MVP pipeline: extract -> load -> soda scan (quality gate) -> dbt seed/run/test."""
    businesses = extract_task()
    load_task(businesses)
    soda_scan_task()
    dbt_seed_task()
    dbt_run_task()
    dbt_test_task()


if __name__ == "__main__":
    dining_radar_pipeline()
