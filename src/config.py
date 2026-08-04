"""Central configuration for local runs and AWS-backed pipeline steps.

This is the only module that reads environment variables.  Paths are resolved
against the project directory so invoking a script from another working
directory cannot silently create a second ``data/`` tree elsewhere.
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_DIR / ".env")


def _project_path(value: str) -> Path:
    """Resolve a configured path without making it depend on the shell cwd."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path


PERIOD_PATTERN = re.compile(r"(?!0000)\d{4}-(0[1-9]|1[0-2])")


def parse_period(value: str) -> tuple[int, int]:
    """Parse an exact ``YYYY-MM`` period."""
    if PERIOD_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Invalid reporting period: {value!r}")
    return int(value[:4]), int(value[5:])


def parse_months(value: str) -> tuple[str, ...]:
    """Parse a comma-separated, ordered list of unique ``YYYY-MM`` periods."""
    months = tuple(part.strip() for part in value.split(",") if part.strip())
    if not months:
        raise ValueError("NYC_LAKE_MONTHS must contain at least one YYYY-MM period")

    invalid = [month for month in months if PERIOD_PATTERN.fullmatch(month) is None]
    if invalid:
        raise ValueError(f"Invalid reporting periods in NYC_LAKE_MONTHS: {invalid}")
    if len(months) != len(set(months)):
        raise ValueError("NYC_LAKE_MONTHS must not contain duplicate periods")
    if months != tuple(sorted(months)):
        raise ValueError("NYC_LAKE_MONTHS must be in ascending chronological order")
    return months


# Environment-specific settings.  There is deliberately no bucket fallback:
# a typo or missing .env must never write into somebody's real bucket.
BUCKET = os.environ.get("NYC_LAKE_BUCKET")
WORKDIR = _project_path(os.environ.get("NYC_LAKE_WORKDIR", "data/workdir"))
RAW_DIR = _project_path(os.environ.get("NYC_LAKE_RAW_DIR", "data/raw_download"))


def require_bucket() -> str:
    """Return the configured bucket or fail before any AWS mutation starts."""
    if not BUCKET:
        raise RuntimeError(
            "NYC_LAKE_BUCKET is not configured. Set it in the environment or project .env file."
        )
    return BUCKET


# lake structure: architecture, deliberately not configurable
RAW_TAXI_PREFIX = "raw/yellow_taxi/"
PROCESSED_TAXI_PREFIX = "processed/yellow_taxi/"
REJECTED_TAXI_PREFIX = "rejected/yellow_taxi/"
QUALITY_TAXI_PREFIX = "reports/yellow_taxi/"
TAXI_MANIFEST_KEY = "_meta/yellow_taxi_manifest.json"

RAW_WEATHER_PREFIX = "raw/weather_hourly/"
PROCESSED_WEATHER_PREFIX = "processed/weather_hourly/"
WEATHER_MANIFEST_KEY = "_meta/weather_manifest.json"

ANALYTICS_TRIPS_WEATHER_PREFIX = "analytics/trips_weather_hourly/"

# Reporting scope.  Override without editing code, for example:
# NYC_LAKE_MONTHS=2024-01,2024-02,2024-03
MONTHS = parse_months(os.environ.get("NYC_LAKE_MONTHS", "2024-01,2024-02,2024-03"))
