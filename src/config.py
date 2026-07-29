"""Central configuration.

The ONLY module in the project that reads environment variables.
Everything environment-specific (bucket, workdir) comes from env with
sane defaults; lake structure (prefixes) is architecture, not config,
so it stays hard-coded here on purpose.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads .env if present; silently does nothing otherwise

# environment-specific (overridable)
BUCKET = os.environ.get("NYC_LAKE_BUCKET", "jakub-nyc-taxi-lake-2026")
WORKDIR = Path(os.environ.get("NYC_LAKE_WORKDIR", "data/workdir"))

# ake structure: architecture, deliberately not configurable
RAW_TAXI_PREFIX = "raw/yellow_taxi/"
PROCESSED_TAXI_PREFIX = "processed/yellow_taxi/"
REJECTED_TAXI_PREFIX = "rejected/yellow_taxi/"
QUALITY_TAXI_PREFIX = "reports/yellow_taxi/"
TAXI_MANIFEST_KEY = "_meta/yellow_taxi_manifest.json"

RAW_WEATHER_PREFIX = "raw/weather_hourly/"
PROCESSED_WEATHER_PREFIX = "processed/weather_hourly/"
WEATHER_MANIFEST_KEY = "_meta/weather_manifest.json"

ANALYTICS_TRIPS_WEATHER_PREFIX = "analytics/trips_weather_hourly/"