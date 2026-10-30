"""Tests for the run log: result parsing and step tracking. BigQuery writes are mocked."""

import datetime as dt
from unittest.mock import patch

import pytest

from src.observability import results, run_log

META = {"run_id": "r1", "flow_name": "f", "recorded_at": "2026-10-30T00:00:00+00:00"}


def test_soda_check_rows_maps_outcomes_and_values():
    scan_results = {"checks": [
        {"name": "row_count > 0", "table": "raw_yelp_restaurants", "outcome": "pass", "diagnostics": {"value": 4600}},
        {"name": "freshness < 100d", "table": "raw_yelp_restaurants", "outcome": "warn", "diagnostics": {"value": "120"}},
        {"name": "out_of_area = 0", "table": "raw_yelp_restaurants", "column": "state", "outcome": "fail"},
        {"name": "broken query", "outcome": None},
    ]}
    rows = results.soda_check_rows(scan_results, **META)

    assert [r["outcome"] for r in rows] == ["pass", "warn", "fail", "not_evaluated"]
    assert rows[0]["observed_value"] == 4600.0
    assert rows[1]["observed_value"] == 120.0
    assert rows[2]["column_name"] == "state"
    assert all(r["tool"] == "soda" and r["run_id"] == "r1" for r in rows)


def test_dbt_test_rows_keeps_tests_only_and_failure_counts():
    run_results = {"results": [
        {"unique_id": "model.dining_radar.dim_restaurants", "status": "success"},
        {"unique_id": "test.dining_radar.not_null_dim_restaurants_id.abc123", "status": "pass", "failures": 0},
        {"unique_id": "test.dining_radar.assert_quarantine_share_below_threshold", "status": "fail",
         "failures": 1, "message": "Got 1 result, configured to fail if != 0"},
        {"unique_id": "test.dining_radar.relationships_city.def456", "status": "warn", "failures": 3},
    ]}
    rows = results.dbt_test_rows(run_results, **META)

    assert len(rows) == 3
    assert rows[0]["check_name"] == "not_null_dim_restaurants_id"
    assert rows[0]["detail"] is None
    assert rows[1]["outcome"] == "fail" and rows[1]["observed_value"] == 1.0
    assert "configured to fail" in rows[1]["detail"]
    assert rows[2]["outcome"] == "warn"


def test_summarize_counts_outcomes_in_fixed_order():
    rows = results.soda_check_rows({"checks": [
        {"name": "a", "outcome": "warn"}, {"name": "b", "outcome": "pass"}, {"name": "c", "outcome": "pass"},
    ]}, **META)
    assert results.summarize(rows) == "soda: 2 pass, 1 warn"
    assert results.summarize([]) == "no checks recorded"


def test_step_row_computes_duration_and_truncates_errors():
    start = dt.datetime(2026, 10, 1, 13, 0, 0, tzinfo=dt.timezone.utc)
    row = results.step_row(run_id="r1", flow_name="f", step="load", status="failed",
                           started_at=start, finished_at=start + dt.timedelta(seconds=2.5),
                           error="x" * 5000)
    assert row["duration_s"] == 2.5
    assert len(row["error"]) == 1000


def test_track_step_records_success_with_details():
    with patch.object(run_log, "write_rows") as write:
        with run_log.track_step("f", "extract") as step:
            step.rows_processed = 42
            step.detail = "ok"
    table, rows = write.call_args.args
    assert table == run_log.RUNS_TABLE
    assert rows[0]["status"] == "success" and rows[0]["rows_processed"] == 42


def test_track_step_records_failure_and_reraises():
    with patch.object(run_log, "write_rows") as write:
        with pytest.raises(ValueError):
            with run_log.track_step("f", "load"):
                raise ValueError("No rows present in the request.")
    row = write.call_args.args[1][0]
    assert row["status"] == "failed"
    assert row["error"] == "ValueError: No rows present in the request."


def test_write_rows_never_raises_when_bigquery_is_unavailable():
    with patch.object(run_log, "_schema", side_effect=RuntimeError("no credentials")):
        run_log.write_rows(run_log.RUNS_TABLE, [{"run_id": "r1"}])  # must not raise


def test_record_dbt_results_handles_missing_file(tmp_path):
    with patch.object(run_log, "write_rows") as write:
        summary = run_log.record_dbt_results("f", tmp_path / "missing.json")
    assert summary == "dbt results not available"
    write.assert_not_called()
