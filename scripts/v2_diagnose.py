"""Read-only health report for DineRadar 2.0 after a run.

Runs a fixed set of SELECT queries against the raw and mart datasets and writes a Markdown
report, so the first real run can be checked against the assumptions in docs/v2-design.md.
Every query is capped by maximum_bytes_billed; nothing is written to BigQuery.

    python -m scripts.v2_diagnose                 # writes run_logs/v2_report_<timestamp>.md
    python -m scripts.v2_diagnose --out report.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

from google.cloud import bigquery

from src.config import BQ_DATASET_MART, BQ_DATASET_RAW, GCP_PROJECT_ID
from src.load.bigquery_loader import get_bigquery_client

MAX_BYTES = 2 * 1024**3  # 2 GiB per query is far above what these tables need
RAW = f"`{GCP_PROJECT_ID}.{BQ_DATASET_RAW}`"
MART = f"`{GCP_PROJECT_ID}.{BQ_DATASET_MART}`"
SNAP = f"`{GCP_PROJECT_ID}.{os.getenv('BQ_DATASET_SNAPSHOTS', 'snapshots')}`"


def t(dataset: str, table: str) -> str:
    return f"{dataset[:-1]}.{table}`"


CHECKS: list[tuple[str, str, str]] = [
    # (section title, what it verifies, SQL)
    ("Raw Overture snapshots per release",
     "One block of rows per monthly release; release label detected from table metadata",
     f"""select snapshot_release, snapshot_date, count(*) as rows_loaded, count(distinct place_id) as places
         from {t(RAW, 'raw_overture_places')} group by 1, 2 order by 2 desc"""),
    ("Raw LA City loads",
     "Incremental Socrata loads arrived; watermark advances",
     f"""select date(_loaded_at) as load_day, count(*) as rows_loaded,
                count(distinct source_row_id) as distinct_rows, max(source_updated_at) as max_source_updated_at
         from {t(RAW, 'raw_la_city_businesses')} group by 1 order by 1 desc"""),
    ("LA City field names (assumption check)",
     "Assumed JSON keys exist in the payload. A null share near 100% means the field name is wrong",
     f"""select count(*) as rows_total,
                round(100 * countif(json_value(payload, '$.location_account') is null) / count(*), 1) as pct_null_location_account,
                round(100 * countif(json_value(payload, '$.business_name') is null) / count(*), 1) as pct_null_business_name,
                round(100 * countif(json_value(payload, '$.naics') is null) / count(*), 1) as pct_null_naics,
                round(100 * countif(json_value(payload, '$.zip_code') is null) / count(*), 1) as pct_null_zip_code,
                round(100 * countif(json_query(payload, '$.location') is null) / count(*), 1) as pct_null_location
         from {t(RAW, 'raw_la_city_businesses')}"""),
    ("LA City payload keys actually present",
     "If an assumed key above is mostly null, the real name is in this list",
     f"""select key, count(*) as rows_with_key
         from {t(RAW, 'raw_la_city_businesses')},
              unnest(regexp_extract_all(payload, r'"([a-z0-9_:@]+)":')) as key
         group by key order by rows_with_key desc limit 40"""),
    ("Overture parsed fields, latest release (assumption check)",
     "JSON paths for name, category, address resolve. High null shares mean a path is wrong",
     f"""with latest as (select max(snapshot_date) d from {t(MART, 'stg_overture__places')})
         select count(*) as food_places,
                round(100 * countif(place_name is null) / count(*), 1) as pct_null_name,
                round(100 * countif(primary_category is null) / count(*), 1) as pct_null_category,
                round(100 * countif(postcode is null) / count(*), 1) as pct_null_postcode,
                round(100 * countif(street_address is null) / count(*), 1) as pct_null_street,
                round(100 * countif(website is null) / count(*), 1) as pct_null_website
         from {t(MART, 'stg_overture__places')}, latest where snapshot_date = latest.d"""),
    ("Overture top categories, latest release",
     "The coarse regex plus is_food_category keeps food places only",
     f"""select primary_category, count(*) as places
         from {t(MART, 'stg_overture__places')}
         where snapshot_date = (select max(snapshot_date) from {t(MART, 'stg_overture__places')})
         group by 1 order by 2 desc limit 20"""),
    ("Overture operating_status, latest release",
     "operating_status field exists and has the expected values",
     f"""select operating_status, count(*) as places
         from {t(MART, 'stg_overture__places')}
         where snapshot_date = (select max(snapshot_date) from {t(MART, 'stg_overture__places')})
         group by 1 order by 2 desc"""),
    ("Overture JSON keys actually present",
     "Top-level keys in the stored payload, to fix any wrong path",
     f"""select key, count(*) as rows_with_key
         from {t(RAW, 'raw_overture_places')},
              unnest(regexp_extract_all(substr(payload, 1, 4000), r'"([a-z_]+)":')) as key
         where snapshot_date = (select max(snapshot_date) from {t(RAW, 'raw_overture_places')})
         group by key order by rows_with_key desc limit 40"""),
    ("LA City staging",
     "Restaurant licenses (NAICS 722) with coordinates; share already closed",
     f"""select count(*) as locations,
                countif(lat is not null) as with_coordinates,
                countif(location_end_date is not null) as with_end_date,
                countif(naics like '722%') as naics_722
         from {t(MART, 'stg_la_city__businesses')}"""),
    ("Snapshot (SCD2) state",
     "Current vs. closed-out versions; after one run every row is current",
     f"""select countif(dbt_valid_to is null) as current_versions, countif(dbt_valid_to is not null) as past_versions
         from {t(SNAP, 'snap_la_city__businesses')}"""),
    ("Entity match rate",
     "Share of Overture places linked to a city license; the singular test warns below 20%",
     f"""select (select count(*) from {t(MART, 'int_overture__place_history')} where is_present_latest) as places_latest,
                count(*) as matched,
                countif(match_confidence = 'high') as high,
                countif(match_confidence = 'medium') as medium,
                countif(match_confidence = 'low') as low
         from {t(MART, 'int_entity__overture_la_city_match')}"""),
    ("Unified status distribution",
     "How often the sources agree; 'conflict' = map says open, registry says closed",
     f"""select unified_status, count(*) as places
         from {t(MART, 'dim_restaurant_v2')} group by 1 order by 2 desc"""),
    ("Churn mart",
     "Openings and closures need at least two releases; one release gives only 'appeared'",
     f"""select snapshot_release, sum(active_places) as active, sum(openings) as openings,
                sum(closures) as closures, sum(status_changes) as status_changes
         from {t(MART, 'mart_zip_release_churn')} group by 1 order by 1 desc"""),
    ("Sample: low-confidence matches (hand review)",
     "Check that these really are the same restaurant",
     f"""select d.place_name, b.business_name, b.dba_name, m.match_score, round(m.distance_m) as distance_m
         from {t(MART, 'int_entity__overture_la_city_match')} m
         join {t(MART, 'dim_restaurant_v2')} d using (place_id)
         join {t(MART, 'stg_la_city__businesses')} b using (location_account)
         where m.match_confidence = 'low' order by rand() limit 15"""),
    ("Sample: conflicts (hand review)",
     "Map says open, registry says closed. Real closures or bad matches?",
     f"""select place_name, street_address, postcode, license_end_date, match_score
         from {t(MART, 'dim_restaurant_v2')} where unified_status = 'conflict' order by rand() limit 15"""),
]


def to_markdown(rows: list[dict]) -> str:
    if not rows:
        return "_no rows_"
    cols = list(rows[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join("" if r[c] is None else str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    parser.add_argument("--out", default=f"run_logs/v2_report_{stamp}.md")
    args = parser.parse_args()

    client = get_bigquery_client()
    config = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES)
    parts = [f"# DineRadar 2.0 run report — {stamp}",
             f"Project `{GCP_PROJECT_ID}` · raw `{BQ_DATASET_RAW}` · mart `{BQ_DATASET_MART}`", ""]
    failures = 0
    for title, why, sql in CHECKS:
        parts += [f"## {title}", f"_{why}_", ""]
        try:
            job = client.query(sql, job_config=config)
            rows = [dict(r.items()) for r in job.result()]
            parts += [to_markdown(rows), f"\n<sub>{(job.total_bytes_billed or 0) / 1e6:.1f} MB billed</sub>", ""]
        except Exception as exc:  # report and continue: a missing table is itself a finding
            failures += 1
            parts += [f"**Query failed:** `{type(exc).__name__}: {str(exc)[:400]}`", ""]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {out} ({len(CHECKS) - failures}/{len(CHECKS)} checks ran)")


if __name__ == "__main__":
    main()
