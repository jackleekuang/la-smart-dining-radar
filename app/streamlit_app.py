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
TRANSACTION_LABELS = {
    "delivery": "Delivery",
    "pickup": "Pickup",
    "restaurant_reservation": "Reservations",
}
TABLE_COLUMNS = [
    "id",
    "name",
    "city",
    "category_titles",
    "transactions",
    "price",
    "rating",
    "review_count",
    "popularity_score",
    "zip_code",
]
DEFAULT_MAP_CENTER = [34.06, -118.28]
DEFAULT_MAP_ZOOM = 11

HELP_TEXT = """
**篩選器(左側)**
- City / Category / Transactions:多選,交集篩選
- 「Filter by open day & time」:選星期+時段,只留當下有營業的餐廳

**表格 → 地圖**
1. 點表格裡的一列選取該餐廳
2. 按「🔍 在地圖上定位選取的餐廳」,地圖會直接跳到該餐廳並標紅星號

**地圖 → 表格**
1. 在地圖上縮放/拖曳到你想看的區域
2. 按「📍 依目前地圖範圍篩選表格」,表格只會顯示目前地圖畫面內的餐廳
3. 按「↺ 清除地圖範圍篩選」恢復顯示全部篩選結果
"""

if "focus_id" not in st.session_state:
    st.session_state.focus_id = None
if "map_bounds" not in st.session_state:
    st.session_state.map_bounds = None
if "use_map_bounds_filter" not in st.session_state:
    st.session_state.use_map_bounds_filter = False


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

all_cities = sorted(df["city"].dropna().unique())
selected_cities = st.sidebar.multiselect("City", all_cities)

all_categories = sorted({c for row in df["category_titles"] for c in (row if row is not None else [])})
selected_categories = st.sidebar.multiselect("Category", all_categories)

all_transactions = sorted({t for row in df["transactions"] for t in (row if row is not None else [])})
selected_transactions = st.sidebar.multiselect(
    "Transactions", all_transactions, format_func=lambda t: TRANSACTION_LABELS.get(t, t)
)

st.sidebar.markdown("---")
filter_by_hours = st.sidebar.checkbox("Filter by open day & time")
selected_day = None
selected_time = None
if filter_by_hours:
    selected_day = st.sidebar.selectbox("Day", DAY_NAMES)
    selected_time = st.sidebar.time_input("Time", value=datetime.time(19, 0))

filtered = df.copy()
if selected_cities:
    filtered = filtered[filtered["city"].isin(selected_cities)]
if selected_categories:
    filtered = filtered[
        filtered["category_titles"].apply(
            lambda cs: any(c in cs for c in selected_categories) if cs is not None else False
        )
    ]
if selected_transactions:
    filtered = filtered[
        filtered["transactions"].apply(
            lambda ts: any(t in ts for t in selected_transactions) if ts is not None else False
        )
    ]

if filter_by_hours and selected_day is not None and selected_time is not None:
    hours_df = load_hours()
    day_hours = hours_df[hours_df["day_of_week"] == DAY_NAMES.index(selected_day)]
    open_mask = day_hours.apply(_is_open_at, axis=1, at_time=selected_time)
    open_ids = set(day_hours.loc[open_mask, "restaurant_id"])
    filtered = filtered[filtered["id"].isin(open_ids)]

# Must be applied here (before the table renders) so the toggle set by the
# button further down takes effect on the rerun it triggers.
if st.session_state.use_map_bounds_filter and st.session_state.map_bounds:
    (south, west), (north, east) = st.session_state.map_bounds
    filtered = filtered[
        filtered["latitude"].between(south, north) & filtered["longitude"].between(west, east)
    ]

st.title("🍽️ LA Smart Dining Radar")
with st.popover("❓ 使用說明"):
    st.markdown(HELP_TEXT)

subtitle = f"{len(filtered)} restaurants"
if len(filtered) != len(df):
    subtitle += f" (of {len(df)} total)"
if st.session_state.use_map_bounds_filter:
    subtitle += " — 已依地圖範圍篩選"
st.subheader(subtitle)

table = filtered[TABLE_COLUMNS].reset_index(drop=True).copy()
table["transactions"] = table["transactions"].apply(
    lambda ts: [TRANSACTION_LABELS.get(t, t) for t in ts] if ts is not None else ts
)
event = st.dataframe(table, width="stretch", on_select="rerun", selection_mode="single-row", key="restaurant_table")

selected_rows = event.selection.rows if event and event.selection else []
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🔍 在地圖上定位選取的餐廳", disabled=not selected_rows):
        st.session_state.focus_id = table.iloc[selected_rows[0]]["id"]
with col2:
    if st.button("📍 依目前地圖範圍篩選表格", disabled=st.session_state.map_bounds is None):
        st.session_state.use_map_bounds_filter = True
        st.rerun()
with col3:
    if st.button("↺ 清除地圖範圍篩選", disabled=not st.session_state.use_map_bounds_filter):
        st.session_state.use_map_bounds_filter = False
        st.rerun()

st.subheader("Map")

focus_row = None
if st.session_state.focus_id is not None:
    match = df[df["id"] == st.session_state.focus_id]
    if not match.empty:
        focus_row = match.iloc[0]

if focus_row is not None:
    m = folium.Map(location=[focus_row["latitude"], focus_row["longitude"]], zoom_start=17)
    folium.Marker(
        location=[focus_row["latitude"], focus_row["longitude"]],
        popup=folium.Popup(f"<b>{focus_row['name']}</b>", max_width=250),
        tooltip=focus_row["name"],
        icon=folium.Icon(color="red", icon="star"),
    ).add_to(m)
else:
    m = folium.Map(location=DEFAULT_MAP_CENTER, zoom_start=DEFAULT_MAP_ZOOM)

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

map_data = st_folium(m, width=1300, height=600, key="main_map")
if map_data and map_data.get("bounds"):
    sw = map_data["bounds"]["_southWest"]
    ne = map_data["bounds"]["_northEast"]
    st.session_state.map_bounds = ((sw["lat"], sw["lng"]), (ne["lat"], ne["lng"]))
