"""Centralized environment/config loading via python-dotenv."""

import os
from dotenv import load_dotenv

load_dotenv()

YELP_API_KEY: str = os.getenv("YELP_API_KEY", "")
GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")
GCP_CREDENTIALS_PATH: str = os.getenv("GCP_CREDENTIALS_PATH", "")
BQ_DATASET_RAW: str = os.getenv("BQ_DATASET_RAW", "raw")
BQ_DATASET_MART: str = os.getenv("BQ_DATASET_MART", "mart")
