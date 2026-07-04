# CLAUDE.md — LA Smart Dining Radar

Development context for continuing this project. Read this first when resuming work.

## What this is

An end-to-end Modern Data Stack (MDS) portfolio project. It extracts high-rated LA
restaurant data from the Yelp Fusion API, lands it in BigQuery, transforms it with
dbt, quality-checks it with Soda + dbt tests, orchestrates the whole run with Prefect,
and serves an interactive Streamlit dashboard (table + Folium map + filters).

GitHub remote: `https://github.com/jackleekuang/la-smart-dining-radar` (public).

## Architecture / data flow

```
Yelp Fusion API
   │  src/extract/yelp_api.py   (paginate curated LA neighborhoods, subdivide for offset-cap budget)
   ▼
BigQuery  raw.raw_yelp_restaurants        (append-only streaming insert; src/load/bigquery_loader.py)
   │  Soda scan  (quality gate on RAW layer only — soda/checks/)
   ▼
dbt  (dbt_project/)
   staging.stg_yelp_restaurants      view   dedup by id (latest ingestion), clean free-text city
   intermediate.int_restaurants_city_mapped  view   apply city_alias_map seed
   marts.dim_restaurants             table  business-ready dim + popularity_score, is_closed=false
   marts.fct_restaurant_hours        table  one row per restaurant per open period (overnight-aware)
   │  dbt test  (quality gate on MART layer — not_null/unique/accepted_values/relationships)
   ▼
Streamlit  app/streamlit_app.py    reads dim_restaurants + fct_restaurant_hours from mart
```

Orchestration order (`src/orchestration/flows.py`, Prefect flow `la-dining-radar-pipeline`):
`extract → load → soda_scan → dbt seed → dbt run → dbt test`. Each dbt/soda step shells
out to the venv binary via `subprocess` with `check=True`, so any failure halts the run.

## Tech stack

Yelp Fusion API · Google BigQuery · Prefect 2 · dbt-core + dbt-bigquery · Soda Core ·
Streamlit + Folium · Python 3.13 · pytest. Pinned in `requirements.txt`.

## Repo layout

```
src/config.py                 env loading (python-dotenv) — single source for secrets/config
src/extract/yelp_api.py       Yelp pagination, neighborhood grid, offset-cap discovery, 429 retry
src/load/bigquery_loader.py   raw-row mapping + 3-way BigQuery auth (see "Auth model")
src/orchestration/flows.py    Prefect flow tying the stages together
app/streamlit_app.py          dashboard (fragments for table/map, hour filter, table→map focus)
dbt_project/                  models (staging/intermediate/marts), seeds, tests, profiles.yml
  seeds/known_la_cities.csv   accepted canonical cities (warn-severity relationships test)
  seeds/city_alias_map.csv    raw→canonical city crosswalk (add a row when a new alias surfaces)
soda/                         raw-layer data-quality checks + connection config
tests/                        pytest: Yelp pagination logic + raw-row mapping (all API/BQ mocked)
Dockerfile                    pipeline image; ENTRYPOINT python -m src.orchestration.flows
raw_yelp_restaurants_schema.json  BigQuery schema for the raw table
```

## Configuration & secrets

`src/config.py` reads these env vars (see `.env.example`):

| Var | Purpose | Default |
| --- | --- | --- |
| `YELP_API_KEY` | Yelp Fusion bearer token | — (required) |
| `GCP_PROJECT_ID` | BigQuery project | — (required) |
| `GCP_CREDENTIALS_PATH` | path to a SA key file (local dev) | `` |
| `BQ_DATASET_RAW` | raw dataset name | `raw` |
| `BQ_DATASET_MART` | mart dataset name | `mart` |
| `PREFECT_API_KEY` | (in `.env`) Prefect Cloud run reporting | — |

Secret files live in the working dir and are **gitignored, never committed** (verified):
`.env`, `gcp-service-account.json` (pipeline SA `dining-radar-pipeline`),
`dashboard-readonly-key.json` (read-only SA `dining-radar-dashboard`).

### Auth model — `get_bigquery_client()` tries three sources in order
1. `GCP_CREDENTIALS_JSON` env var holding **raw key JSON** — for Streamlit Community
   Cloud, which only accepts pasted secrets. `streamlit_app.py` mirrors `st.secrets`
   into env before importing `src.config`. (Note: paste the key as a JSON **string**,
   not a TOML table, or `json.loads` will fail — `str()` of a table isn't JSON.)
2. `GCP_CREDENTIALS_PATH` key file — local dev.
3. Application Default Credentials from an attached identity — Cloud Run.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in YELP_API_KEY, GCP_PROJECT_ID, GCP_CREDENTIALS_PATH

# individual stages
python -m src.extract.yelp_api          # dry-run fetch, prints counts
python -m src.load.bigquery_loader      # fetch + load raw
dbt seed  --project-dir dbt_project --profiles-dir dbt_project
dbt run   --project-dir dbt_project --profiles-dir dbt_project
dbt test  --project-dir dbt_project --profiles-dir dbt_project
soda scan -d dining_radar -c soda/configuration.yml soda/checks/raw_yelp_restaurants.yml

# full pipeline
python -m src.orchestration.flows

# dashboard
streamlit run app/streamlit_app.py

# tests
python -m pytest -q
```

Note `dbt profiles.yml` lives inside `dbt_project/` (not `~/.dbt`); always pass
`--profiles-dir dbt_project`. It picks `service-account` vs `oauth` based on whether
`GCP_CREDENTIALS_PATH` is set.

## Deployment (current setup — verify exact resource names in GCP console)

- **Pipeline:** `Dockerfile` → container image → **Cloud Run**, triggered **quarterly by
  Cloud Scheduler**. In Cloud Run it uses auth path #3 (attached service identity / ADC),
  so no key file is baked into the image (Dockerfile copies only `src/ dbt_project/ soda/`).
- **Dashboard:** **Streamlit Community Cloud**, BigQuery auth via `st.secrets` →
  `GCP_CREDENTIALS_JSON` (the read-only dashboard SA). App is public.

There is currently **no** `cloudbuild.yaml` / deploy script in the repo — build & deploy
steps are manual. Documenting/scripting them is a good next task.

## Known issues & next steps

1. **Remove the DEBUG caption in `app/streamlit_app.py` (lines ~28–32).** It prints the
   list of secret key-names and `GCP_PROJECT_ID`/dataset to every visitor of the public
   dashboard. Leftover from diagnosing a Streamlit Cloud `NotFound`. Delete it.
2. **Raw load is append-only streaming insert.** Every quarterly run re-appends all
   fetched rows; the raw table grows unbounded, streaming-buffered rows can't be deleted
   for ~90 min, and one `insert_rows_json` call sends all rows in a single request (risk
   of the ~10 MB/request limit on a large pull). Marts stay correct (dbt dedups by latest
   `ingestion_timestamp`). Consider batch load jobs + partition/`MERGE`, and chunking inserts.
3. **README.md is a spec/template, not current docs** — raw-schema table is stale, has a
   "Project Structure … to be generated" placeholder, and no setup/run/deploy instructions.
   Refresh it (or point it at this file).
4. No CI / linter / pre-commit. Tests (6) pass and cover extract + raw mapping only; there
   is no test for the Streamlit layer beyond dbt's own tests.

## Conventions

- All Python has type hints + concise docstrings; secrets only via env (never hardcoded).
- New unrecognized cities surface via the warn-severity `known_la_cities` relationships
  test — add the canonical name to `known_la_cities.csv` and, if it's an alias, a row to
  `city_alias_map.csv`. Don't hardcode city fixes in SQL.
- Duplicates are expected from overlapping neighborhood queries and are deduped in dbt
  staging, not in the extractor.
