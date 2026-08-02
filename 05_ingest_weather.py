"""
Ingest raw Open-Meteo monthly JSON into s3 raw/weather_hourly/.

Freshness model: presence-based (no ETag equivalent for API responses),
so historical corrections by the API are NOT auto-detected; use --force.
"""

import argparse
import json
import logging
from datetime import UTC, datetime

# variables from env file: 
from src.config import (
    BUCKET,
    RAW_WEATHER_PREFIX,
    WEATHER_MANIFEST_KEY,
)
from src.logging_setup import setup_logging
from src.manifest import load_manifest, save_manifest
from src.s3_io import s3
from src.weather import fetch_weather_month
from src.config import MONTHS


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    setup_logging("ingest_weather")
    args = parse_args()
    manifest = load_manifest(BUCKET, WEATHER_MANIFEST_KEY)

    for month_str in MONTHS:
        filename = f"weather_{month_str}.json"
        if filename in manifest and not args.force:
            logging.info("SKIP %s (manifest)", filename)
            continue
        year, month = int(month_str[:4]), int(month_str[5:7])
        payload = fetch_weather_month(year, month)
        s3.put_object(
            Bucket=BUCKET, Key=RAW_WEATHER_PREFIX + filename,
            Body=json.dumps(payload).encode("utf-8"),
        )
        logging.info("UPLOAD s3://%s/%s%s", BUCKET, RAW_WEATHER_PREFIX, filename)
        manifest[filename] = {
            "ingested_at_utc": datetime.now(UTC).isoformat(),
            "hours_in_payload": len(payload["hourly"]["time"]),
        }
        save_manifest(manifest, BUCKET, WEATHER_MANIFEST_KEY)