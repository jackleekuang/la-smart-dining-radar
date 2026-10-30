"""Turn Soda scan results and dbt run_results.json into rows for the run-log tables.

Standard library only, so these functions can be unit-tested without BigQuery, Soda or
dbt installed. The BigQuery side lives in run_log.py.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

# Outcomes stored in dq_check_results.outcome
PASS, WARN, FAIL, ERROR, SKIPPED, NOT_EVALUATED = "pass", "warn", "fail", "error", "skipped", "not_evaluated"

_DBT_STATUS = {"pass": PASS, "warn": WARN, "fail": FAIL, "error": ERROR, "skipped": SKIPPED}


def utc_now_iso() -> str:
    """Current UTC time as an ISO 8601 string (what BigQuery JSON loads accept for TIMESTAMP)."""
    return dt.datetime.now(dt.timezone.utc).isoformat()


def truncate(text: str | None, limit: int = 1000) -> str | None:
    """Cap free text so one huge error message cannot bloat the log table."""
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _to_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def soda_check_rows(scan_results: dict[str, Any], *, run_id: str, flow_name: str, recorded_at: str) -> list[dict]:
    """One row per Soda check from Scan.get_scan_results().

    Soda reports outcome pass / warn / fail, or None when the check could not be
    evaluated (for example its query errored). None is stored as not_evaluated
    rather than guessed.
    """
    rows = []
    for check in scan_results.get("checks") or []:
        outcome = str(check.get("outcome") or "").lower()
        diagnostics = check.get("diagnostics") or {}
        rows.append({
            "run_id": run_id,
            "flow_name": flow_name,
            "recorded_at": recorded_at,
            "tool": "soda",
            "check_name": truncate(check.get("name") or check.get("definition") or "unnamed check", 300),
            "target": check.get("table"),
            "column_name": check.get("column"),
            "outcome": outcome if outcome in (PASS, WARN, FAIL) else NOT_EVALUATED,
            "observed_value": _to_float(diagnostics.get("value")),
            "detail": None,
        })
    return rows


def dbt_test_rows(run_results: dict[str, Any], *, run_id: str, flow_name: str, recorded_at: str) -> list[dict]:
    """One row per dbt test from target/run_results.json (models, seeds and snapshots are skipped).

    observed_value is the number of failing rows dbt counted, which is what a
    reviewer wants to see next to a warn or fail.
    """
    rows = []
    for result in run_results.get("results") or []:
        unique_id = str(result.get("unique_id") or "")
        if not unique_id.startswith("test."):
            continue
        parts = unique_id.split(".")
        status = str(result.get("status") or "").lower()
        rows.append({
            "run_id": run_id,
            "flow_name": flow_name,
            "recorded_at": recorded_at,
            "tool": "dbt",
            "check_name": parts[2] if len(parts) > 2 else unique_id,
            "target": None,
            "column_name": None,
            "outcome": _DBT_STATUS.get(status, ERROR),
            "observed_value": _to_float(result.get("failures")),
            "detail": truncate(result.get("message"), 500) if status != "pass" else None,
        })
    return rows


def summarize(check_rows: list[dict]) -> str:
    """Short text for the step row, e.g. 'soda: 11 pass, 1 warn'."""
    if not check_rows:
        return "no checks recorded"
    counts = Counter(row["outcome"] for row in check_rows)
    order = [PASS, WARN, FAIL, ERROR, NOT_EVALUATED, SKIPPED]
    tool = check_rows[0]["tool"]
    return f"{tool}: " + ", ".join(f"{counts[o]} {o}" for o in order if counts[o])


def step_row(
    *,
    run_id: str,
    flow_name: str,
    step: str,
    status: str,
    started_at: dt.datetime,
    finished_at: dt.datetime,
    rows_processed: int | None = None,
    detail: str | None = None,
    error: str | None = None,
    run_url: str | None = None,
) -> dict:
    """One row for pipeline_runs: a single step (task attempt) of a flow run."""
    return {
        "run_id": run_id,
        "flow_name": flow_name,
        "step": step,
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_s": round((finished_at - started_at).total_seconds(), 3),
        "rows_processed": rows_processed,
        "detail": truncate(detail, 500),
        "error": truncate(error),
        "run_url": run_url,
    }
