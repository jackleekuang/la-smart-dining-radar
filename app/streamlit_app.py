"""Streamlit front-end for LA Smart Dining Radar."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import datetime

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from src.config import BQ_DATASET_MART, GCP_PROJECT_ID
from src.load.bigquery_loader import get_bigquery_client

st.set_page_config(page_title="LA Smart Dining Radar", layout="wide")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@st.cache_data(ttl=600)
def load_dim_restaurants() -> pd.DataFrame:
    """Query the dim_restaurants mart table into a DataFrame."""
    client = get_bigquery_client()
    query = f"""
        SELECT *
        FROM `{GCP_PROJECT_ID}.{BQ_DATASET_MART}.dim_restaurants`
        ORDER BY popularity_score DESC
    """
    return client.query(query).to_dataframe()


@st.cache_data(ttl=600)
def load_hours() -> pd.DataFrame:
    """Query the fct_restaurant_hours mart table into a DataFrame."""
    client = get_bigquery_client()
    query = f"SELECT * FROM `{GCP_PROJECT_ID}.{BQ_DATASET_MART}.fct_restaurant_hours`"
    return client.query(query).to_dataframe()


def _is_open_at(row: pd.Series, at_time: datetime.time) -> bool:
    """Check whether a single fct_restaurant_hours row covers at_time, handling overnight wraparound."""
    if row["is_overnight"]:
        return at_time >= row["start_time"] or at_time <= row["end_time"]
    return row["start_time"] <= at_time <= row["end_time"]


df = load_dim_restaurants()

st.sidebar.header("Filters")

all_transactions = sorted({t for row in df["transactions"] for t in (row if row is not None else [])})
selected_transactions = st.sidebar.multiselect("Transactions", all_transactions)

all_cities = sorted(df["city"].dropna().unique())
selected_cities = st.sidebar.multiselect("City", all_cities)

st.sidebar.markdown("---")
filter_by_hours = st.sidebar.checkbox("Filter by open day & time")
selected_day = None
selected_time = None
if filter_by_hours:
    selected_day = st.sidebar.selectbox("Day", DAY_NAMES)
    selected_time = st.sidebar.time_input("Time", value=datetime.time(19, 0))

filtered = df.copy()
if selected_transactions:
    filtered = filtered[
        filtered["transactions"].apply(
            lambda ts: any(t in ts for t in selected_transactions) if ts is not None else False
        )
    ]
if selected_cities:
    filtered = filtered[filtered["city"].isin(selected_cities)]

if filter_by_hours and selected_day is not None and selected_time is not None:
    hours_df = load_hours()
    day_hours = hours_df[hours_df["day_of_week"] == DAY_NAMES.index(selected_day)]
    open_mask = day_hours.apply(_is_open_at, axis=1, at_time=selected_time)
    open_ids = set(day_hours.loc[open_mask, "restaurant_id"])
    filtered = filtered[filtered["id"].isin(open_ids)]

st.title("🍽️ LA Smart Dining Radar")

subtitle = f"{len(filtered)} restaurants"
if len(filtered) != len(df):
    subtitle += f" (of {len(df)} total)"
st.subheader(subtitle)
st.dataframe(filtered, width="stretch")

st.subheader("Map")
m = folium.Map(location=[34.06, -118.28], zoom_start=11)
cluster = MarkerCluster().add_to(m)
for _, row in filtered.iterrows():
    if pd.isna(row["latitude"]) or pd.isna(row["longitude"]):
        continue
    popup_html = (
        f"<b>{row['name']}</b><br>"
        f"⭐ {row['rating']} ({row['review_count']} reviews)<br>"
        f"{row['price']}<br>"
        f"{row['address1']}, {row['city']}"
    )
    folium.Marker(
        location=[row["latitude"], row["longitude"]],
        popup=folium.Popup(popup_html, max_width=250),
        tooltip=row["name"],
    ).add_to(cluster)
st_folium(m, width=1300, height=600)
