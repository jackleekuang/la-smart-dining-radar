# Handoff — state as of 2026-10-28

Written at the end of a claude.ai working session so work can continue in Claude Code.
Read `CLAUDE.md` first for architecture and conventions; this file is the *current status*.

## Where things stand

| Item | State |
| --- | --- |
| PR #1 remove DEBUG caption + docs | merged |
| PR #2 data-quality contract (service-area quarantine, rating 0 → NULL, singular tests, Soda exit codes, CI) | merged (`14a1e3d`), CI green |
| PR #3 | closed, superseded by #4 |
| PR #4 open-hours fix (`app/hours.py`), Yelp credit, map `returned_objects=[]` | merged |
| PR #5 `perf/fast-marker-cluster` — FastMarkerCluster + HTML-escaped popup/tooltip (`src/app_helpers.map_points`) | **open**, CI green, **not yet verified in a browser** |
| Branch `v2-open-data` — Overture + LA City open-data pipeline | 2 commits ahead / several behind `main`; **never run against BigQuery**; trial merge conflicts only in `dbt_project/dbt_project.yml` |

Nothing in v1 has been re-run against BigQuery since PR #2 merged. The DQ changes were
validated only by `dbt parse` in CI plus pure-Python tests.

## Next steps, in order

1. **Verify v1 on BigQuery** (from repo root, venv active, `.env` filled):
   ```bash
   dbt seed  --project-dir dbt_project --profiles-dir dbt_project
   dbt build --project-dir dbt_project --profiles-dir dbt_project
   ```
   Expect everything PASS. Then check that `dq_restaurants_quarantine` contains the
   Saint Clairsville (Ohio Pizza Hut) and Monte Rio rows with a `service_area_issue`,
   and that neither appears in `dim_restaurants`.
2. **Soda:** `soda scan -d dining_radar -c soda/configuration.yml soda/checks/raw_yelp_restaurants.yml`
   (exit code 1 = warnings only, expected to be tolerated by the flow).
3. **Verify PR #5 locally:** `git checkout perf/fast-marker-cluster && streamlit run app/streamlit_app.py`.
   Check that pan/zoom is smooth, popups open on click, tooltips show on hover. Then merge.
4. **v2 first run:**
   ```bash
   git checkout v2-open-data
   pip install -r requirements.txt      # upgrades to Prefect 3
   bash scripts/v2_first_run.sh
   ```
   Read `run_logs/<timestamp>/summary.txt` and `report.md`. Expect at least one field-path
   fix in the Overture/Socrata staging SQL. Record: Overture restaurant count, LA City
   registry count, match rate; hand-check ~30 matches for precision.
5. Rebase `v2-open-data` on `main` (resolve `dbt_project.yml`: keep both var blocks), add
   v2 tests to CI, then merge.
6. Later: second Overture monthly release (first open/close events), Streamlit v2 page
   (unified status map, conflict list, churn by ZIP), DataHub ingestion of dbt artifacts
   + BigQuery, retire or re-scope v1 for Yelp terms.

## v2 design in one paragraph

Sources: `bigquery-public-data.overture_maps.place` (only the latest release is kept, so
we build our own history) and LA City business registry (Socrata `r4uk-afju`, NAICS 722).
Raw landing → Soda gate (freshness, ±30% row volume) → dbt: staging → snapshot
`snap_la_city__businesses` (SCD2) → intermediate (`int_overture__place_history`,
`int_overture__place_events`, `int_entity__overture_la_city_match`: ZIP + 150 m blocking,
score 0.60 name + 0.25 street number + 0.15 distance, min 0.6, one-to-one) → marts
`dim_restaurant_v2` (contracted; `unified_status` ∈ open_confirmed / open_unverified /
conflict / temporarily_closed / closed_confirmed / closed_unverified) and
`mart_zip_release_churn`. Orchestrated by Prefect 3 flow `dineradar-v2-landscape`
(`src/orchestration/flows_v2.py`, cron `0 9 8 * *`). Full design: `docs/v2-design.md`
on the v2 branch.

## Why v2 exists (context for interviews)

Yelp API terms allow caching content for at most 24 h and forbid building a business
database; v1's append-only raw table violates that. v2 uses open data and is framed as a
multi-vendor reconciliation problem: entity match ≈ security master, snapshots ≈
point-in-time / restatements, `conflict` status ≈ vendor reconciliation, Soda volume gate
≈ vendor file anomaly, quarantine gate ≈ the Ohio Pizza Hut incident. Be explicit that
dbt/Prefect/Soda experience comes from this project, not from the TCR nonprofit role
(which used BigQuery + Streamlit).

## Environment notes

- The claude.ai cloud sandbox could not reach PyPI or GCP, so none of the above was run
  there; run everything locally where `.env` and the SA key files live.
- `gh pr create` (GraphQL) was blocked in that sandbox; REST `gh api` worked.
