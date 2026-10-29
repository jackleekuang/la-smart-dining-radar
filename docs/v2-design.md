# DineRadar 2.0 — LA Restaurant Landscape Monitor

Status: **in development on branch `v2-open-data`**. v1 (Yelp dashboard) is unchanged and still runs from `main`.

## Problem

Two public sources describe the same LA restaurants, and they disagree:

| Source | What it knows | How it changes |
|---|---|---|
| **Overture Maps Places** (BigQuery public dataset) | Which places exist on the map, category, address, coordinates, operating status | Monthly releases. The public mirror keeps **only the latest release** |
| **LA City business registry** (Office of Finance, Socrata `r4uk-afju`) | Licensed business locations, NAICS code, start and end dates | Rows are **overwritten in place** (an end date appears when a business closes) |

Questions the project answers:
1. Which restaurants are open right now, according to both sources together?
2. Where do the sources disagree (the map says open, the registry says closed)?
3. How many restaurants opened and closed per ZIP code each month?

Why this framing: it is the same shape of problem a quant data team handles every day.
Several vendors describe the same entity with different ids, the vendors revise or drop history,
and the team needs to know "what did we know as of date X" without look-ahead bias.

v1's Yelp data could not support this. The Fusion API terms restrict storing content, and the
Yelp Open Dataset does not cover Los Angeles. Overture Places is released under permissive
licenses (CDLA Permissive 2.0 / Apache 2.0), so storing it is allowed.

## Architecture

```
bigquery-public-data.overture_maps.place ──(monthly INSERT…SELECT, LA bbox, dry-run cost guard)──┐
                                                                                                  ▼
LA City Socrata API ──(incremental by :updated_at, batch load job, task retries)──► BigQuery raw (JSON payloads)
                                                                                                  │
                                                     Soda: schema / freshness / volume vs. last release
                                                                                                  ▼
dbt (tag:v2)
  staging       stg_overture__places          one row per place per release (parsed from JSON)
                stg_la_city__businesses       latest record per business location
  snapshot      snap_la_city__businesses      SCD2 — the city overwrites rows in place
  intermediate  int_overture__place_history   lifecycle per place (replayable from raw)
                int_overture__place_events    appeared / disappeared / status & category changes
                int_entity__overture_la_city_match   entity resolution, one-to-one
  marts         dim_restaurant_v2  (contract)  unified status, including explicit 'conflict'
                mart_zip_release_churn        openings / closures per ZIP per release
                                                                                                  ▼
                                                                          Streamlit page (next step)
Orchestration: Prefect 3 flow `dineradar-v2-landscape`, monthly (`serve`, cron 0 9 8 * *)
```

## Why each tool is here (the "remove it and what breaks" test)

| Tool | Job it owns in v2 | Without it |
|---|---|---|
| **BigQuery** | Overture already lives in BigQuery public data, so it can be read without copying files; partitioned raw tables keep the snapshot history | We would have to download GeoParquet files ourselves and host them somewhere |
| **dbt** | JSON parsing that tolerates schema drift, SCD2 snapshot, history and events derived from immutable snapshots, entity resolution, tests, an enforced contract on the mart | Ordering, testing and lineage across 8 models would be hand-rolled |
| **Prefect** | Two sources with different behaviour; retries on the HTTP source only; idempotent per-release reloads (`--force-overture`); one monthly schedule and run history | A cron job could not retry one step, skip an already-loaded release, or give one run history |
| **Soda** | Checks on what arrives from outside before any transformation: required columns and types, freshness, release-over-release volume (±30%), duplicate ids in the latest release, upstream id field still present | dbt tests cover our model logic; these upstream checks would either be missing or tangled into the models |

## Key decisions

1. **Land JSON payloads (ELT), parse in dbt.** Overture renames fields between releases and its
   BigQuery mirror nests arrays as `list[].element`. Storing the whole row means a rename never
   loses data at load time. The `json_coalesce` macro lists every known path, and Soda plus dbt
   tests catch fields that go missing.
2. **Two different history strategies, on purpose.**
   - Overture: the history is already immutable per release in raw, so it is derived in SQL and
     can be **rebuilt from scratch** at any time.
   - LA City: the source overwrites rows, so a **dbt snapshot** is the only way to keep history.
     (A dbt snapshot cannot be backfilled, which is why it is not used for Overture.)
3. **Cost guard.** The snapshot scans a large public table. Every query is dry-run first. The run
   fails if the estimate exceeds `OVERTURE_MAX_BYTES_BILLED` (default 200 GiB), and the same limit
   is set as `maximum_bytes_billed` on the real job.
4. **Idempotency.** A release that is already loaded is skipped. A forced reload deletes that
   release first. LA City loads append and are de-duplicated in staging by the latest `:updated_at`.
5. **Disagreement is a status, not a bug.** `unified_status = 'conflict'` keeps the cases where
   the sources disagree visible. They are not resolved silently.

## Assumptions to verify on the first real run

| Assumption | How it is checked |
|---|---|
| Overture BigQuery field paths (`taxonomy.primary` / `basic_category` / `categories.primary`, `addresses.list[0].element.*`) | Run `dbt build -s stg_overture__places`, then check null rates of `primary_category` and `postcode` |
| The release version appears in the table labels | `detect_release` falls back to the table's last-modified date |
| LA City field names (`location_account`, `naics`, `location`, …) | The Soda check `payload_missing_account_pct` and `not_null` on `location_account` |
| Soda resolves unqualified table names in user-defined metric SQL to the configured dataset | First `soda scan` |
| Matching thresholds (150 m, score ≥ 0.6) | Hand-review 30 matches per confidence tier; the singular test warns if the match rate is < 20% |

## First run results (2026-10-29)

Three assumptions were wrong, all found by actually running against live data (not caught by
`dbt parse`/unit tests, which don't touch the network or BigQuery):

1. **LA City `naics` is a Socrata `number`, not text.** The extractor built `naics like '722%'`,
   which Socrata rejects outright (400) against a numeric column. Fixed by matching a numeric
   range instead (`naics >= 722000 AND naics < 723000` — codes are fixed-width 6 digits):
   `src/v2/socrata.py`, with `tests/test_v2_socrata.py` updated to match.
2. **Socrata SoQL requires `*` first in `$select`.** `":id, :updated_at, *"` is a syntax error
   ("Star selections must come at the start of the select-list"); reordered to `"*, :id, :updated_at"`
   in the same file.
3. **Coordinates are at `location.latitude`/`location.longitude`, not `location_1.*`.** Confirmed
   against the live Socrata payload. Fixed in `stg_la_city__businesses.sql` and the matching
   assumption check in `scripts/v2_diagnose.py`. Before the fix, 0/24,995 LA City rows had
   coordinates, so the entity-match step could not match anything; after the fix, 21,263/24,995
   (85%) do — the rest appear to be genuinely un-geocoded source rows (payload has no `location`
   key at all), not a parsing bug.

One more thing the fix didn't automatically resolve: `snap_la_city__businesses` (the dbt
snapshot that gives LA City data SCD2 history) had already been created on the first *successful*
dbt build, while the coordinate bug was still live — so it locked in all-NULL `lat`/`lon` for
every row. dbt snapshots only add a new version when `source_updated_at` changes, so re-running
`dbt build` after the code fix did not refresh the bad data already in the snapshot. Since this
was the first snapshot ever built (`past_versions: 0`, nothing of value to lose), Jack approved
dropping `la-smart-dining-radar.snapshots.snap_la_city__businesses` and letting dbt rebuild it
clean on the next run.

**Numbers, after all three fixes and the snapshot rebuild:**

- Overture: 37,994 places loaded for release `2026-10-21`, 33,821 of them food places
  (one-time load scanned ~53.7 GiB of the public table — well under the 200 GiB cap; the
  release is cached after first load, so re-running `v2_first_run.sh` doesn't re-scan it).
- LA City: 24,995 current business-license locations with NAICS 722 (restaurants), 362 already
  closed (`location_end_date` set), 21,263 (85%) with usable coordinates.
- Entity match rate: 6,279 / 33,821 Overture places matched to a city license (18.6% — high
  confidence 4,043, medium 1,216, low 1,020). This is just under the 20% dbt-warn threshold.
  Hand-reviewing the low-confidence sample (e.g. "MOD Pizza" vs. legal name "MOD SUPERFAST PIZZA
  (CALIFORNIA) LLC", distance 67 m) shows real restaurants with a chain/common name that differs
  more from the registered legal or DBA name than `normalize_name` can close — not a
  normalization bug. Per the sprint rules, the 150 m / 0.6 thresholds were left untouched;
  this is flagged here for Jack to decide whether 18.6% is acceptable or the thresholds should
  be revisited (most non-matches are simply Overture places with no corresponding city license
  in this NAICS-722 extract, which is expected — a lot of LA restaurants are unlicensed or
  licensed under a different NAICS code such as a shared commercial-kitchen catch-all).
- `unified_status` on `dim_restaurant_v2` (33,821 rows): `open_unverified` 25,660,
  `open_confirmed` 5,888, `closed_unverified` 2,177, `conflict` 87, `closed_confirmed` 9.
- `dbt build --select tag:v2`: 36 pass, 1 warn (`assert_match_rate_reasonable`, expected given
  the 18.6% match rate above), 0 errors. Soda scan on the raw layer: 12/12 checks passed.
- Churn: only one Overture release has been loaded so far, so `mart_zip_release_churn` shows
  33,374 active places and 0 openings/closures/status changes for this release — expected;
  openings/closures need at least two months of snapshots to say anything (see the note at the
  bottom of `INTERVIEW_SPRINT.md`).

## Run book

First real run, every step logged and a read-only health report at the end:

```bash
bash scripts/v2_first_run.sh        # writes run_logs/<timestamp>/summary.txt and report.md
```

Individual commands:

```bash
pip install -r requirements.txt
export GCP_PROJECT_ID=... BQ_DATASET_RAW=raw BQ_DATASET_MART=mart GCP_CREDENTIALS_PATH=...

python -m src.orchestration.flows_v2                      # one run
python -m src.orchestration.flows_v2 --force-overture     # reload the current release
python -m src.orchestration.flows_v2 --serve              # monthly schedule (Prefect 3)

dbt build --select tag:v2 --project-dir dbt_project --profiles-dir dbt_project
soda scan -d dining_radar -c soda/configuration.yml soda/checks/v2_raw_overture_places.yml
python -m pytest -q tests/test_v2_*.py
```

## Next steps

- [x] First real run; resolve the assumptions above — see "First run results (2026-10-29)"
- [ ] Streamlit page: unified status map, conflict list, churn per ZIP
- [ ] DataHub: ingest BigQuery + dbt (`manifest.json`, `catalog.json`, `run_results.json`), and
      Prefect lineage via `prefect-datahub`
- [ ] GitHub Actions: pytest, plus `dbt build --select state:modified+` against a dev dataset
