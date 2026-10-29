"""DineRadar 2.0 — open-data landscape monitor (Overture Maps + LA City business licenses)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import html
import os

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

# Same env mirroring as app/streamlit_app.py — harmless to repeat if that page already
# ran in this process, and needed if a user lands here first via a direct link.
try:
    for _key, _value in st.secrets.items():
        os.environ.setdefault(_key, str(_value))
except st.errors.StreamlitSecretNotFoundError:
    pass

from src.config import BQ_DATASET_MART, GCP_PROJECT_ID
from src.load.bigquery_loader import get_bigquery_client

st.set_page_config(page_title="DineRadar 2.0 | Landscape", page_icon="🗺️", layout="wide")

STATUS_COLORS = {
    "open_confirmed": "#2ca02c",
    "open_unverified": "#98df8a",
    "conflict": "#d62728",
    "temporarily_closed": "#ff7f0e",
    "closed_confirmed": "#000000",
    "closed_unverified": "#7f7f7f",
}
STATUS_LABELS = {
    "open_confirmed": "Open — confirmed by both sources",
    "open_unverified": "Open — map only, no license match",
    "conflict": "Conflict — map says open, registry says closed",
    "temporarily_closed": "Temporarily closed",
    "closed_confirmed": "Closed — confirmed by both sources",
    "closed_unverified": "Closed — map only, no license match",
}


@st.cache_data(ttl=3600)
def load_dim_restaurant_v2() -> pd.DataFrame:
    """Query the dim_restaurant_v2 mart table into a DataFrame."""
    client = get_bigquery_client()
    query = f"SELECT * FROM `{GCP_PROJECT_ID}.{BQ_DATASET_MART}.dim_restaurant_v2`"
    return client.query(query).to_dataframe()


@st.cache_data(ttl=3600)
def load_zip_release_churn() -> pd.DataFrame:
    """Query the mart_zip_release_churn mart table into a DataFrame."""
    client = get_bigquery_client()
    query = f"SELECT * FROM `{GCP_PROJECT_ID}.{BQ_DATASET_MART}.mart_zip_release_churn`"
    return client.query(query).to_dataframe()


# streamlit-folium silently fails to render (a JS syntax error in the component's
# postMessage payload, confirmed empirically: 5,000 markers render fine, 15,000 don't)
# once too many individual markers are embedded, regardless of clustering -- clustering
# happens client-side, so every marker still has to ship to the browser. Keep the rarer,
# more interesting statuses in full and sample the rest down to this budget.
MAX_MAP_MARKERS = 5000


def _sample_for_map(df: pd.DataFrame, cap: int = MAX_MAP_MARKERS) -> pd.DataFrame:
    located = df.dropna(subset=["lat", "lon"])
    if len(located) <= cap:
        return located
    rare = located[located["unified_status"].isin(["conflict", "closed_confirmed"])]
    remaining_budget = max(cap - len(rare), 0)
    common = located.drop(rare.index)
    sample = common.sample(n=min(remaining_budget, len(common)), random_state=0)
    return pd.concat([rare, sample])


def _build_map(df: pd.DataFrame) -> folium.Map:
    located = df
    m = folium.Map(location=[34.06, -118.28], zoom_start=10)
    cluster = MarkerCluster().add_to(m)
    for _, row in located.iterrows():
        # Place names routinely contain apostrophes (Dunkin', McDonald's, ...), which break
        # the tooltip's generated JS unless escaped first.
        name = html.escape(str(row["place_name"]))
        status = html.escape(STATUS_LABELS.get(row["unified_status"], row["unified_status"]))
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=5,
            color=STATUS_COLORS.get(row["unified_status"], "#1f77b4"),
            fill=True,
            fill_opacity=0.8,
            tooltip=f"{name} — {status}",
        ).add_to(cluster)
    return m


st.title("🗺️ DineRadar 2.0 — Open Data Landscape")
st.markdown(
    "Cross-references Overture Maps place data against LA City business licenses "
    "(NAICS 722, restaurants) to flag where the two sources agree, disagree, or can't be matched."
)

dim_df = load_dim_restaurant_v2()
churn_df = load_zip_release_churn()

latest_release = churn_df["snapshot_release"].max() if len(churn_df) else None
status_counts = dim_df["unified_status"].value_counts()

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Data version", latest_release or "–")
kpi2.metric("Total places", f"{len(dim_df):,}")
kpi3.metric("Open (either status)", f"{status_counts.filter(like='open').sum():,}")
kpi4.metric("Conflicts", f"{status_counts.get('conflict', 0):,}")

st.caption(" · ".join(f"**{STATUS_LABELS.get(s, s)}**: {n:,}" for s, n in status_counts.items()))

st.subheader("⚠️ Sources disagree")
st.markdown("Map says open, LA City registry says the license ended — real closure or a bad match?")
conflicts = dim_df[dim_df["unified_status"] == "conflict"][
    ["place_name", "street_address", "postcode", "license_end_date", "match_score"]
].sort_values("license_end_date", ascending=False)
if conflicts.empty:
    st.caption("No conflicts in the latest data.")
else:
    st.dataframe(conflicts.reset_index(drop=True), width="stretch")

st.subheader("Map")
map_points = _sample_for_map(dim_df)
caption = "Colored by unified status. Panning/zooming does not rerun the app."
if len(map_points) < len(dim_df):
    caption += (
        f" Showing {len(map_points):,} of {len(dim_df):,} places (all conflicts and "
        "closed-confirmed included; the rest sampled) — more would break the map."
    )
st.caption(caption)
m = _build_map(map_points)
st_folium(m, height=600, use_container_width=True, returned_objects=[], key="landscape_map")

st.subheader("Openings & closures by ZIP")
n_releases = churn_df["snapshot_release"].nunique() if len(churn_df) else 0
if n_releases < 2:
    st.info(
        "Only one Overture release has been loaded so far — churn (openings/closures) needs "
        "at least two months of snapshots to mean anything. This will fill in after the next "
        "monthly run."
    )
else:
    latest_churn = churn_df[churn_df["snapshot_release"] == latest_release]
    st.dataframe(
        latest_churn[["postcode", "active_places", "openings", "closures", "net_change"]]
        .sort_values("net_change")
        .reset_index(drop=True),
        width="stretch",
    )

st.markdown("---")
st.caption(
    "Data sources: Overture Maps Foundation (Places) · City of Los Angeles Office of Finance "
    "(business licenses, NAICS 722)."
)
