"""Write pipeline steps and data-quality results to BigQuery so the dashboard can show them.

Two append-only tables in the mart dataset (the read-only dashboard account can already
read it):

- pipeline_runs     one row per step attempt: status, rows, duration, error, Prefect link
- dq_check_results  one row per Soda check or dbt test: pass / warn / fail and the value

Logging must never break the pipeline. Every write is wrapped; a failed write is only
logged as a warning.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from src.config import BQ_DATASET_MART, GCP_PROJECT_ID
from src.observability.results import dbt_test_rows, soda_check_rows, step_row, summarize, utc_now_iso

RUNS_TABLE = "pipeline_runs"
CHECKS_TABLE = "dq_check_results"

logger = logging.getLogger(__name__)


def table_id(name: str) -> str:
    """Fully qualified id for a run-log table in the mart dataset."""
    return f"{GCP_PROJECT_ID}.{BQ_DATASET_MART}.{name}"


def _schema(table_name: str) -> tuple[list, str]:
    """BigQuery schema and partition column for a run-log table."""
    from google.cloud import bigquery

    field = bigquery.SchemaField
    if table_name == RUNS_TABLE:
        return [
            field("run_id", "STRING", mode="REQUIRED"),
            field("flow_name", "STRING"),
            field("step", "STRING"),
            field("status", "STRING"),
            field("started_at", "TIMESTAMP"),
            field("finished_at", "TIMESTAMP"),
            field("duration_s", "FLOAT"),
            field("rows_processed", "INTEGER"),
            field("detail", "STRING"),
            field("error", "STRING"),
            field("run_url", "STRING"),
        ], "started_at"
    return [
        field("run_id", "STRING", mode="REQUIRED"),
        field("flow_name", "STRING"),
        field("recorded_at", "TIMESTAMP"),
        field("tool", "STRING"),
        field("check_name", "STRING"),
        field("target", "STRING"),
        field("column_name", "STRING"),
        field("outcome", "STRING"),
        field("observed_value", "FLOAT"),
        field("detail", "STRING"),
    ], "recorded_at"


def write_rows(table_name: str, rows: list[dict]) -> None:
    """Append rows with a batch load job (free, no streaming buffer). Never raises."""
    if not rows:
        return
    try:
        from google.cloud import bigquery

        from src.load.bigquery_loader import get_bigquery_client

        schema, partition_field = _schema(table_name)
        client = get_bigquery_client()
        table = bigquery.Table(table_id(table_name), schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(field=partition_field)
        client.create_table(table, exists_ok=True)
        client.load_table_from_json(
            rows,
            table_id(table_name),
            job_config=bigquery.LoadJobConfig(
                schema=schema, write_disposition=bigquery.WriteDisposition.WRITE_APPEND
            ),
        ).result()
    except Exception as exc:  # the run log is best-effort by design
        logger.warning("Run log: could not write %s row(s) to %s: %s", len(rows), table_name, exc)


def current_run() -> tuple[str, str | None]:
    """Prefect flow-run id and UI link, or a random id when running outside Prefect."""
    try:
        from prefect.runtime import flow_run

        run_id = flow_run.id
        if run_id:
            url = getattr(flow_run, "ui_url", None)
            return str(run_id), str(url) if url else None
    except Exception:
        pass
    return uuid.uuid4().hex, None


@dataclass
class StepRecord:
    """What a step reports about itself; filled in inside a track_step block."""

    status: str = "success"
    rows_processed: int | None = None
    detail: str | None = None


@contextlib.contextmanager
def track_step(flow_name: str, step: str) -> Iterator[StepRecord]:
    """Record one pipeline_runs row for the wrapped block: success, warned or failed.

    Exceptions are recorded with their message and then re-raised unchanged, so
    Prefect still sees the failure and stops the flow.
    """
    run_id, run_url = current_run()
    record = StepRecord()
    started = dt.datetime.now(dt.timezone.utc)

    def _write(status: str, error: str | None) -> None:
        write_rows(RUNS_TABLE, [step_row(
            run_id=run_id, flow_name=flow_name, step=step, status=status,
            started_at=started, finished_at=dt.datetime.now(dt.timezone.utc),
            rows_processed=record.rows_processed, detail=record.detail, error=error, run_url=run_url,
        )])

    try:
        yield record
    except Exception as exc:
        _write("failed", f"{type(exc).__name__}: {exc}")
        raise
    _write(record.status, None)


def record_soda_results(flow_name: str, scan_results: dict[str, Any]) -> str:
    """Store every Soda check outcome; return a one-line summary for the step row."""
    run_id, _ = current_run()
    rows = soda_check_rows(scan_results, run_id=run_id, flow_name=flow_name, recorded_at=utc_now_iso())
    write_rows(CHECKS_TABLE, rows)
    return summarize(rows)


def record_dbt_results(flow_name: str, run_results_path: Path) -> str:
    """Store every dbt test outcome from run_results.json; return a one-line summary."""
    try:
        run_results = json.loads(run_results_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Run log: could not read %s: %s", run_results_path, exc)
        return "dbt results not available"
    run_id, _ = current_run()
    rows = dbt_test_rows(run_results, run_id=run_id, flow_name=flow_name, recorded_at=utc_now_iso())
    write_rows(CHECKS_TABLE, rows)
    return summarize(rows)
