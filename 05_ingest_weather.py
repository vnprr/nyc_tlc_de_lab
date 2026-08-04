"""Fetch validated monthly Open-Meteo JSON into a deterministic raw key.

Normal runs keep the existing object.  ``--force`` deliberately replaces it.
For this single-writer portfolio pipeline, history should later be provided by
S3 Versioning rather than a custom content-addressed snapshot system.
"""

import argparse
import hashlib
import json
import logging
from datetime import UTC, datetime

from src.config import (
    MONTHS,
    RAW_WEATHER_PREFIX,
    WEATHER_MANIFEST_KEY,
    parse_period,
    require_bucket,
)
from src.logging_setup import setup_logging
from src.manifest import load_manifest, save_manifest
from src.s3_io import object_exists, s3
from src.weather import (
    fetch_weather_month,
    manifest_weather_digest,
    process_weather_payload,
    validate_raw_weather_metadata,
)

LOGGER = logging.getLogger(__name__)


def run(*, periods: tuple[str, ...] = MONTHS, force: bool = False) -> None:
    bucket = require_bucket()
    manifest = load_manifest(bucket, WEATHER_MANIFEST_KEY)

    for period in periods:
        year, month = parse_period(period)
        raw_key = f"{RAW_WEATHER_PREFIX}weather_{period}.json"
        entry = manifest.get(period)
        raw_exists = object_exists(bucket, raw_key)
        if not force and raw_exists:
            try:
                expected_digest = manifest_weather_digest(entry, raw_key)
                remote = s3.head_object(Bucket=bucket, Key=raw_key)
                validate_raw_weather_metadata(remote.get("Metadata"), expected_digest)
            except ValueError as error:
                raise RuntimeError(
                    f"Raw weather and its manifest disagree for {period}; "
                    "inspect it and use --force only if replacement is intentional"
                ) from error
            LOGGER.info("SKIP weather %s (raw object exists)", period)
            continue

        payload = fetch_weather_month(year, month)
        process_weather_payload(payload, year, month)  # validate before raw promotion
        content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()

        s3.put_object(
            Bucket=bucket,
            Key=raw_key,
            Body=content,
            ContentType="application/json",
            Metadata={"sha256": digest, "period": period},
        )
        manifest[period] = {
            "raw_key": raw_key,
            "content_sha256": digest,
            "ingested_at_utc": datetime.now(UTC).isoformat(),
            "hours_in_payload": len(payload["hourly"]["time"]),
        }
        save_manifest(manifest, bucket, WEATHER_MANIFEST_KEY)
        LOGGER.info("WRITE weather %s -> s3://%s/%s", period, bucket, raw_key)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    setup_logging("ingest_weather")
    run(force=parse_args().force)


if __name__ == "__main__":
    main()
