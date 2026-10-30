"""Prefect flow orchestrating extract -> load -> soda scan -> dbt seed/run/test.

Every step writes a row to mart.pipeline_runs, and every Soda check and dbt test writes
a row to mart.dq_check_results (src/observability/run_log.py), so the dashboard can show
what ran, what passed and what the quality gates stopped.
"""

import subprocess
import sys
from pathlib import Path
from typing import Any

from prefect import flow, get_run_logger, task

from src.extract.yelp_api import fetch_all_restaurants
from src.load.bigquery_loader import load_restaurants
from src.observability.run_log import record_dbt_results, record_soda_results, track_step
from src.orchestration.soda_exit import SodaOutcome, interpret_soda_exit_code

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = Path(sys.executable).parent
DBT_DIR = PROJECT_ROOT / "dbt_project"
FLOW_NAME = "la-dining-radar-pipeline"


def _dbt(command: str) -> subprocess.CompletedProcess:
    """Run one dbt command against the project; the caller decides what a failure means."""
    return subprocess.run(
        [str(VENV_BIN / "dbt"), command, "--project-dir", "dbt_project", "--profiles-dir", "dbt_project"],
        cwd=PROJECT_ROOT,
        check=False,
    )


@task
def extract_task() -> list[dict[str, Any]]:
    """Fetch restaurant listings from the Yelp Fusion API across all core neighborhoods."""
    with track_step(FLOW_NAME, "extract") as step:
        businesses = fetch_all_restaurants()  # raises on a Yelp error or an empty batch
        step.rows_processed = len(businesses)
        step.detail = f"{len({b['id'] for b in businesses})} distinct restaurants"
    return businesses


@task
def load_task(businesses: list[dict[str, Any]]) -> None:
    """Load fetched restaurant records into BigQuery's raw layer."""
    with track_step(FLOW_NAME, "load") as step:
        load_restaurants(businesses)
        step.rows_processed = len(businesses)


@task
def soda_scan_task() -> None:
    """Run Soda Core data quality checks against the raw layer.

    Warn-level checks (e.g. a few out-of-area records, slightly stale data) are
    logged and the run continues; fail-level checks or scan errors stop it.
    Every check outcome is stored before that decision, so a stopped run still
    shows which check stopped it.
    """
    from src.orchestration.runtime_env import ensure_distutils

    ensure_distutils()
    from soda.scan import Scan

    with track_step(FLOW_NAME, "soda_scan") as step:
        scan = Scan()
        scan.set_data_source_name("dining_radar")
        scan.add_configuration_yaml_file(str(PROJECT_ROOT / "soda" / "configuration.yml"))
        scan.add_sodacl_yaml_file(str(PROJECT_ROOT / "soda" / "checks" / "raw_yelp_restaurants.yml"))
        exit_code = scan.execute()
        get_run_logger().info(scan.get_logs_text())
        step.detail = record_soda_results(FLOW_NAME, scan.get_scan_results())

        outcome = interpret_soda_exit_code(exit_code)
        if outcome is SodaOutcome.WARNED:
            step.status = "warned"
            get_run_logger().warning("Soda raw-layer scan passed with warnings: %s", step.detail)
        elif outcome is SodaOutcome.FAILED:
            raise RuntimeError(f"Soda raw-layer scan failed (exit code {exit_code}): {step.detail}")


@task
def dbt_seed_task() -> None:
    """Load dbt seeds (e.g. the city alias/reference lookups) into BigQuery."""
    with track_step(FLOW_NAME, "dbt_seed"):
        if _dbt("seed").returncode != 0:
            raise RuntimeError("dbt seed failed")


@task
def dbt_run_task() -> None:
    """Run dbt models to (re)build the mart layer from the raw layer."""
    with track_step(FLOW_NAME, "dbt_run"):
        if _dbt("run").returncode != 0:
            raise RuntimeError("dbt run failed")


@task
def dbt_test_task() -> None:
    """Run dbt tests to validate the mart layer after a rebuild.

    Failures here (e.g. too many quarantined rows) are the pipeline's main
    quality gate against the mart layer -- distinct from soda_scan_task, which
    only guards the raw layer before any transformation runs. Results are
    stored first, then a failure stops the run.
    """
    with track_step(FLOW_NAME, "dbt_test") as step:
        result = _dbt("test")
        step.detail = record_dbt_results(FLOW_NAME, DBT_DIR / "target" / "run_results.json")
        if result.returncode != 0:
            raise RuntimeError(f"dbt test failed: {step.detail}")
        if " warn" in step.detail:
            step.status = "warned"


@flow(name=FLOW_NAME)
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
