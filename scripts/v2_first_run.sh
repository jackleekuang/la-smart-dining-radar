#!/usr/bin/env bash
# First real run of DineRadar 2.0, with every step logged.
#
#   bash scripts/v2_first_run.sh
#
# Needs .env with GCP_PROJECT_ID, BQ_DATASET_RAW, BQ_DATASET_MART and GCP_CREDENTIALS_PATH
# (Soda's BigQuery connection reads the key file). Writes run_logs/<timestamp>/, which is
# gitignored. A step that fails is recorded and the script moves on, so one run shows
# every problem at once.
#
# Cost: the Overture snapshot scans a public table; the flow dry-runs it first and refuses
# to run above OVERTURE_MAX_BYTES_BILLED (default 200 GiB). Everything else is small.

set -u
cd "$(dirname "$0")/.."
STAMP=$(date +%Y%m%d_%H%M)
LOG_DIR="run_logs/$STAMP"
mkdir -p "$LOG_DIR"
SUMMARY="$LOG_DIR/summary.txt"

if [ -f .env ]; then set -a; . ./.env; set +a; fi
for v in GCP_PROJECT_ID BQ_DATASET_RAW BQ_DATASET_MART; do
  if [ -z "${!v:-}" ]; then echo "Missing $v in .env" | tee -a "$SUMMARY"; exit 1; fi
done

step() {
  local name="$1"; shift
  echo "==> $name"
  local start=$SECONDS
  if "$@" >"$LOG_DIR/$name.log" 2>&1; then
    echo "PASS  $name  ($((SECONDS - start))s)" | tee -a "$SUMMARY"
  else
    echo "FAIL  $name  ($((SECONDS - start))s)  see $LOG_DIR/$name.log" | tee -a "$SUMMARY"
    tail -n 15 "$LOG_DIR/$name.log"
  fi
}

step 01_versions        bash -c 'python --version; dbt --version; prefect version; soda --version 2>/dev/null || pip show soda-core-bigquery | head -2'
step 02_unit_tests      python -m pytest -q tests
step 03_dbt_debug       dbt debug --project-dir dbt_project --profiles-dir dbt_project
step 04_dbt_parse       dbt parse --project-dir dbt_project --profiles-dir dbt_project
# The flow: Overture snapshot -> LA City load -> Soda gate -> dbt build --select tag:v2
step 05_flow            python -m src.orchestration.flows_v2
step 06_source_freshness dbt source freshness --select source:raw_v2 --project-dir dbt_project --profiles-dir dbt_project
step 07_diagnose        python -m scripts.v2_diagnose --out "$LOG_DIR/report.md"

echo
echo "Done. Summary: $SUMMARY   Report: $LOG_DIR/report.md"
cat "$SUMMARY"
