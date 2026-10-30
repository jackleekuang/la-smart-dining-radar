"""Pipeline health: what ran, what passed, and what the quality gates stopped.

Reads the run log the pipelines write (mart.pipeline_runs, mart.dq_check_results) and the
v1 quarantine table. Nothing here writes to BigQuery.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import os
import re

import pandas as pd
import streamlit as st

# Same env mirroring as app/streamlit_app.py, needed if a visitor lands here first.
try:
    for _key, _value in st.secrets.items():
        os.environ.setdefault(_key, str(_value))
except st.errors.StreamlitSecretNotFoundError:
    pass

from src.config import BQ_DATASET_MART, GCP_PROJECT_ID
from src.load.bigquery_loader import get_bigquery_client

st.set_page_config(page_title="DineRadar | Pipeline Health", page_icon="🩺", layout="wide")

MART = f"`{GCP_PROJECT_ID}.{BQ_DATASET_MART}`"
STATUS_ICON = {"success": "✅", "warned": "⚠️", "failed": "❌"}
OUTCOME_ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌", "error": "❌", "not_evaluated": "❔", "skipped": "⏭️"}


@st.cache_data(ttl=300)
def query(sql: str) -> pd.DataFrame | None:
    """Run a read-only query; None when the table does not exist yet."""
    try:
        return get_bigquery_client().query(sql).to_dataframe()
    except Exception as exc:  # NotFound before the first logged run
        if "Not found" in str(exc) or "NotFound" in type(exc).__name__:
            return None
        raise


st.title("🩺 Pipeline Health")
st.markdown(
    "Every pipeline step and every data-quality check is logged to BigQuery. "
    "This page shows what ran, what passed, and what the quality gates stopped."
)

with st.expander("What each tool does here"):
    st.markdown(
        "| Tool | Job | Stops the run when |\n|---|---|---|\n"
        "| **Prefect** | Runs the steps in order, retries flaky sources, records each run | any step raises |\n"
        "| **Soda** | Checks the raw layer before any transformation | a fail-level check fires (warnings are logged, the run continues) |\n"
        "| **dbt tests** | Checks the published tables after the rebuild | a test fails (e.g. more than 2% of open restaurants quarantined) |\n"
        "| **Quarantine** | Withholds rows that break the service-area contract, with a reason | never: rows are set aside, not dropped |"
    )
    st.caption(
        "Schedules as configured on 2026-10-30: v1 (Yelp) runs from Cloud Scheduler, "
        "`0 6 1 1,4,7,10 *` America/Los_Angeles (6 am on Jan/Apr/Jul/Oct 1). "
        "v2 (open data) has no schedule yet."
    )

# ---- Recent runs -----------------------------------------------------------------------
runs = query(f"""
    select run_id, any_value(flow_name) as flow_name, min(started_at) as started_at,
           max(finished_at) as finished_at,
           case when countif(status = 'failed') > 0 then 'failed'
                when countif(status = 'warned') > 0 then 'warned' else 'success' end as status,
           string_agg(step || ' ' || status, ' → ' order by started_at) as steps,
           any_value(run_url) as run_url
    from {MART}.pipeline_runs
    where started_at >= timestamp_sub(current_timestamp(), interval 400 day)
    group by run_id
    order by started_at desc
    limit 50
""")

if runs is None or runs.empty:
    st.info(
        "No runs logged yet. The run log tables are created by the first pipeline run "
        "that includes this logging."
    )
    st.stop()

latest = runs.iloc[0]
cols = st.columns(4)
cols[0].metric("Last run", f"{STATUS_ICON.get(latest.status, '')} {latest.status}")
cols[1].metric("Last run started (UTC)", pd.Timestamp(latest.started_at).strftime("%Y-%m-%d %H:%M"))
cols[2].metric("Runs logged", len(runs))
cols[3].metric("Failed runs", int((runs["status"] == "failed").sum()))

st.subheader("Recent runs")
shown = runs.assign(status=runs["status"].map(lambda s: f"{STATUS_ICON.get(s, '')} {s}"))
st.dataframe(
    shown[["started_at", "flow_name", "status", "steps", "run_url"]],
    hide_index=True,
    use_container_width=True,
    column_config={
        "started_at": st.column_config.DatetimeColumn("Started (UTC)", format="YYYY-MM-DD HH:mm"),
        "run_url": st.column_config.LinkColumn("Prefect", display_text="open"),
    },
)

# ---- One run in detail -------------------------------------------------------------------
st.subheader("Run detail")
labels = {
    r.run_id: f"{pd.Timestamp(r.started_at).strftime('%Y-%m-%d %H:%M')} · {r.flow_name} · {r.status}"
    for r in runs.itertuples()
}
run_id = st.selectbox("Run", list(labels), format_func=labels.get)
safe_id = re.sub(r"[^A-Za-z0-9-]", "", str(run_id))  # run ids are UUIDs or hex

steps = query(f"""
    select step, status, rows_processed, duration_s, detail, error, started_at
    from {MART}.pipeline_runs where run_id = '{safe_id}' order by started_at
""")
if steps is not None:
    st.dataframe(
        steps.assign(status=steps["status"].map(lambda s: f"{STATUS_ICON.get(s, '')} {s}")).drop(columns="started_at"),
        hide_index=True,
        use_container_width=True,
    )

checks = query(f"""
    select tool, check_name, target, outcome, observed_value, detail
    from {MART}.dq_check_results where run_id = '{safe_id}'
    order by case outcome when 'fail' then 0 when 'error' then 1 when 'warn' then 2
                          when 'not_evaluated' then 3 else 4 end, tool, check_name
""")
if checks is None or checks.empty:
    st.caption("No data-quality checks were reached in this run (an earlier step stopped it).")
else:
    counts = checks["outcome"].value_counts()
    st.caption(" · ".join(f"{OUTCOME_ICON.get(o, '')} {o}: {n}" for o, n in counts.items()))
    st.dataframe(
        checks.assign(outcome=checks["outcome"].map(lambda o: f"{OUTCOME_ICON.get(o, '')} {o}")),
        hide_index=True,
        use_container_width=True,
    )

# ---- What the gates caught -----------------------------------------------------------------
st.subheader("What the quality gates caught")
caught = query(f"""
    select date(recorded_at) as day, flow_name, tool, check_name, outcome, observed_value
    from {MART}.dq_check_results
    where outcome != 'pass'
    order by recorded_at desc
    limit 200
""")
if caught is None or caught.empty:
    st.caption("No warnings or failures recorded.")
else:
    st.dataframe(caught, hide_index=True, use_container_width=True)

quarantine = query(f"""
    select service_area_issue as reason, count(*) as restaurants
    from {MART}.dq_restaurants_quarantine group by 1 order by 2 desc
""")
if quarantine is not None and not quarantine.empty:
    st.markdown("**Withheld from the dashboard (v1 quarantine), by reason**")
    st.dataframe(quarantine, hide_index=True)
