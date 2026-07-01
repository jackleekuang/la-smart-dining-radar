"""Streamlit front-end for LA Smart Dining Radar."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from src.config import BQ_DATASET_MART, GCP_PROJECT_ID
from src.load.bigquery_loader import get_bigquery_client

st.set_page_config(page_title="LA Smart Dining Radar", layout="wide")


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


st.title("🍽️ LA Smart Dining Radar")

df = load_dim_restaurants()
st.subheader(f"{len(df)} restaurants")
st.dataframe(df, use_container_width=True)

st.subheader("Map")
st.map(df.rename(columns={"latitude": "lat", "longitude": "lon"})[["lat", "lon"]])
