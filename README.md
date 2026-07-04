# 🍽️ LA Smart Dining Radar

An end-to-end **Modern Data Stack (MDS)** project that discovers and analyzes high-rated
restaurants across Los Angeles. It extracts data from the Yelp Fusion API, warehouses it
in BigQuery, transforms it with dbt, quality-checks it with Soda + dbt tests, orchestrates
the run with Prefect, and serves an interactive Streamlit dashboard (searchable table +
Folium map + filters).

## 🛠️ Tech Stack

| Layer | Tool |
| :--- | :--- |
| Extraction | Yelp Fusion API (Python `requests`) |
| Warehouse | Google BigQuery |
| Orchestration | Prefect 2 |
| Transformation | dbt Core (`dbt-bigquery`) |
| Data Quality | Soda Core (raw layer) + dbt tests (mart layer) |
| Dashboard | Streamlit + Folium |
| Runtime / Test | Python 3.13 · pytest |

## 🧭 Architecture

```
Yelp Fusion API
   │  extract   curated LA neighborhoods, subdivided to stretch Yelp's offset cap
   ▼
BigQuery  raw.raw_yelp_restaurants        append-only landing table
   │  Soda scan   quality gate on the RAW layer
   ▼
dbt
   staging      stg_yelp_restaurants            (view)  dedup by latest ingestion, clean free-text city
   intermediate int_restaurants_city_mapped     (view)  map city aliases via seed
   marts        dim_restaurants                 (table) business-ready dim + popularity_score
                fct_restaurant_hours            (table) one row per restaurant per open period
   │  dbt test   quality gate on the MART layer
   ▼
Streamlit dashboard   reads dim_restaurants + fct_restaurant_hours
```

Prefect flow (`src/orchestration/flows.py`) runs the stages in order and halts on any
failure: `extract → load → soda scan → dbt seed → dbt run → dbt test`.

## 🗄️ Data Models

**`raw.raw_yelp_restaurants`** — raw Yelp payload (append-only). Full schema in
[`dbt_project/raw_yelp_restaurants_schema.json`](dbt_project/raw_yelp_restaurants_schema.json):
`id, name, rating, review_count, price, categories, latitude, longitude,
ingestion_timestamp, is_closed, address1–3, city, zip_code, state, country,
transactions, business_hours`.

**`mart.dim_restaurants`** — cleaned, deduplicated dimension (open restaurants only).
Adds `category_titles` (parsed from Yelp categories JSON), a canonicalized `city`
(alongside the original `city_raw`), and a calculated **`popularity_score`**
= `round(rating * ln(review_count + 1), 3)` — a weighted metric so a 4.8★/2000-review
spot outranks a 5.0★/3-review one.

**`mart.fct_restaurant_hours`** — `business_hours` exploded to one row per restaurant per
open period, with parsed `start_time`/`end_time` and an `is_overnight` flag (so the
dashboard's "open at this day & time" filter handles past-midnight hours correctly).

**Seeds** — `known_la_cities.csv` (accepted canonical cities) and `city_alias_map.csv`
(raw→canonical crosswalk). A warn-severity dbt relationships test surfaces any new/unknown
city so it can be added to the seeds instead of silently skewing the dashboard.

## 🔐 Configuration

Copy `.env.example` → `.env` and fill in:

| Var | Purpose |
| :--- | :--- |
| `YELP_API_KEY` | Yelp Fusion bearer token |
| `GCP_PROJECT_ID` | BigQuery project id |
| `GCP_CREDENTIALS_PATH` | path to a GCP service-account key file (local dev) |
| `BQ_DATASET_RAW` / `BQ_DATASET_MART` | dataset names (default `raw` / `mart`) |

No secrets are hardcoded. Credential files (`*-key.json`, `.env`) are gitignored.
`get_bigquery_client()` authenticates via, in order: `GCP_CREDENTIALS_JSON` (raw JSON
string, for Streamlit Community Cloud) → `GCP_CREDENTIALS_PATH` key file (local) →
Application Default Credentials (Cloud Run).

## 🚀 Getting Started

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill in your keys

# run the full pipeline (extract → load → quality checks → transform)
python -m src.orchestration.flows

# or run stages individually
python -m src.load.bigquery_loader                                   # extract + load raw
dbt seed --project-dir dbt_project --profiles-dir dbt_project
dbt run  --project-dir dbt_project --profiles-dir dbt_project
dbt test --project-dir dbt_project --profiles-dir dbt_project
soda scan -d dining_radar -c soda/configuration.yml soda/checks/raw_yelp_restaurants.yml

# launch the dashboard
streamlit run app/streamlit_app.py

# run tests
python -m pytest -q
```

> dbt's `profiles.yml` lives inside `dbt_project/` — always pass `--profiles-dir dbt_project`.

## ☁️ Deployment

- **Pipeline** — the [`Dockerfile`](Dockerfile) builds a container
  (`ENTRYPOINT python -m src.orchestration.flows`) deployed to **Cloud Run** and triggered
  **quarterly by Cloud Scheduler**. On Cloud Run it authenticates via the attached service
  identity (ADC), so no key file is baked into the image.
- **Dashboard** — deployed to **Streamlit Community Cloud**; BigQuery auth comes from
  `st.secrets` (`GCP_CREDENTIALS_JSON`, a read-only service account).

## 📂 Project Structure

```
src/
  config.py                  env/config loading
  extract/yelp_api.py        Yelp pagination + neighborhood grid + offset-cap handling
  load/bigquery_loader.py    raw-row mapping + BigQuery auth/insert
  orchestration/flows.py     Prefect flow
app/streamlit_app.py         dashboard
dbt_project/                 models (staging/intermediate/marts), seeds, tests, profiles
soda/                        raw-layer data-quality checks
tests/                       pytest (Yelp pagination + raw-row mapping; API/BQ mocked)
Dockerfile                   pipeline container image
```

## 🧑‍💻 Development Notes

For architecture details, the auth model, deployment specifics, and the running
"known issues / next steps" list, see [`CLAUDE.md`](CLAUDE.md).
