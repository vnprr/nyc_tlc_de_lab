"""Transform configured raw weather JSON into typed monthly Parquet files.

Weather is small, so a deterministic full recompute is clearer than a second
manifest and a state machine for derived files.
"""

import hashlib
import json
import logging

from src.config import (
    MONTHS,
    PROCESSED_WEATHER_PREFIX,
    RAW_WEATHER_PREFIX,
    WEATHER_MANIFEST_KEY,
    WORKDIR,
    parse_period,
    require_bucket,
)
from src.logging_setup import setup_logging
from src.manifest import load_manifest
from src.s3_io import s3, upload_df_overwrite
from src.weather import WEATHER_TRANSFORM_VERSION, manifest_weather_digest, process_weather_payload

LOGGER = logging.getLogger(__name__)


def run(*, periods: tuple[str, ...] = MONTHS) -> None:
    bucket = require_bucket()
    manifest = load_manifest(bucket, WEATHER_MANIFEST_KEY)

    for period in periods:
        year, month = parse_period(period)
        expected_raw_key = f"{RAW_WEATHER_PREFIX}weather_{period}.json"
        expected_digest = manifest_weather_digest(manifest.get(period), expected_raw_key)

        content = s3.get_object(Bucket=bucket, Key=expected_raw_key)["Body"].read()
        observed_digest = hashlib.sha256(content).hexdigest()
        if observed_digest != expected_digest:
            raise ValueError(f"Raw weather SHA-256 mismatch for {period}")

        payload = json.loads(content)
        frame = process_weather_payload(payload, year, month)
        output_key = (
            f"{PROCESSED_WEATHER_PREFIX}year={year}/month={month:02d}/weather_{period}.parquet"
        )
        upload_df_overwrite(
            frame,
            bucket,
            output_key,
            WORKDIR,
            metadata={
                "source-weather-sha256": observed_digest,
                "weather-transform-version": WEATHER_TRANSFORM_VERSION,
            },
        )
        LOGGER.info("PROCESSED weather %s", period)


def main() -> None:
    setup_logging("process_weather")
    run()


if __name__ == "__main__":
    main()
