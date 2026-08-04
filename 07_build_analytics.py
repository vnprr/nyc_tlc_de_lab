"""Build hourly taxi aggregates joined with weather.

Because taxi files retain a seven-day boundary margin, a complete event month
``M`` requires source files ``M-1``, ``M`` and ``M+1``.  With the default
January to March source scope, only February is publishable.
"""

import logging
import tempfile
from pathlib import Path

import pandas as pd

from src.analytics import build_trips_weather_hourly
from src.config import (
    ANALYTICS_TRIPS_WEATHER_PREFIX,
    MONTHS,
    PROCESSED_TAXI_PREFIX,
    PROCESSED_WEATHER_PREFIX,
    RAW_TAXI_PREFIX,
    RAW_WEATHER_PREFIX,
    TAXI_MANIFEST_KEY,
    WEATHER_MANIFEST_KEY,
    WORKDIR,
    parse_period,
    require_bucket,
)
from src.coverage import publishable_periods, required_source_periods
from src.logging_setup import setup_logging
from src.manifest import get_raw_etag, load_manifest, manifest_output_keys, processing_reason
from src.s3_io import delete_keys, download_file, s3, upload_df_overwrite
from src.transform import TRANSFORM_VERSION
from src.weather import (
    manifest_weather_digest,
    validate_processed_weather_metadata,
    validate_raw_weather_metadata,
)

LOGGER = logging.getLogger(__name__)


def analytics_output_key(period: str) -> str:
    year, month = parse_period(period)
    return (
        f"{ANALYTICS_TRIPS_WEATHER_PREFIX}year={year}/month={month:02d}/"
        f"trips_weather_{period}.parquet"
    )


def current_taxi_partition_keys(
    event_period: str,
    *,
    bucket: str,
    manifest: dict,
) -> list[str]:
    """Select current processed files for one complete event-time partition."""
    year, month = parse_period(event_period)
    partition_prefix = f"{PROCESSED_TAXI_PREFIX}year={year}/month={month:02d}/"
    keys = []

    for source_period in required_source_periods(event_period):
        filename = f"yellow_tripdata_{source_period}.parquet"
        raw_key = f"{RAW_TAXI_PREFIX}{filename}"
        raw_etag = get_raw_etag(bucket, raw_key)
        reason = processing_reason(
            filename,
            raw_etag,
            manifest,
            transform_version=TRANSFORM_VERSION,
            source_key=raw_key,
            bucket=bucket,
        )
        if reason is not None:
            raise RuntimeError(f"Taxi source {source_period} is not current: {reason}")

        keys.extend(
            key
            for key in manifest_output_keys(filename, manifest[filename])
            if key.startswith(partition_prefix) and key.endswith(f"/{filename}")
        )

    keys = sorted(set(keys))
    if not keys:
        raise FileNotFoundError(f"No taxi data found for event month {event_period}")
    return keys


def read_parquet_keys(
    keys: list[str],
    *,
    bucket: str,
    scratch: Path,
) -> pd.DataFrame:
    frames = []
    for index, key in enumerate(keys):
        local_path = scratch / f"input-{index:03d}.parquet"
        download_file(bucket, key, local_path)
        frames.append(pd.read_parquet(local_path))
    if not frames:
        raise FileNotFoundError("No Parquet inputs selected")
    return pd.concat(frames, ignore_index=True)


def build_month(
    period: str,
    *,
    bucket: str,
    taxi_manifest: dict,
    weather_manifest: dict,
) -> None:
    year, month = parse_period(period)
    taxi_keys = current_taxi_partition_keys(period, bucket=bucket, manifest=taxi_manifest)
    raw_weather_key = f"{RAW_WEATHER_PREFIX}weather_{period}.json"
    weather_digest = manifest_weather_digest(weather_manifest.get(period), raw_weather_key)
    weather_key = (
        f"{PROCESSED_WEATHER_PREFIX}year={year}/month={month:02d}/weather_{period}.parquet"
    )
    raw_metadata = s3.head_object(Bucket=bucket, Key=raw_weather_key).get("Metadata")
    validate_raw_weather_metadata(raw_metadata, weather_digest)
    processed_metadata = s3.head_object(Bucket=bucket, Key=weather_key).get("Metadata")
    validate_processed_weather_metadata(processed_metadata, weather_digest)

    WORKDIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORKDIR, prefix=f"analytics-{period}-") as directory:
        scratch = Path(directory)
        trips = read_parquet_keys(taxi_keys, bucket=bucket, scratch=scratch)
        weather_local = scratch / f"weather_{period}.parquet"
        download_file(bucket, weather_key, weather_local)
        weather = pd.read_parquet(weather_local)
        result = build_trips_weather_hourly(trips, weather, year, month)

    upload_df_overwrite(result, bucket, analytics_output_key(period), WORKDIR)
    LOGGER.info("BUILT analytics %s", period)


def run(*, source_periods: tuple[str, ...] = MONTHS) -> None:
    bucket = require_bucket()
    publish_periods = publishable_periods(source_periods)
    if not publish_periods:
        raise ValueError("At least three consecutive source months are required for analytics")

    excluded = [period for period in source_periods if period not in publish_periods]
    if excluded:
        LOGGER.warning("Coverage-only source months will not be published: %s", excluded)

    taxi_manifest = load_manifest(bucket, TAXI_MANIFEST_KEY)
    weather_manifest = load_manifest(bucket, WEATHER_MANIFEST_KEY)
    for period in publish_periods:
        build_month(
            period,
            bucket=bucket,
            taxi_manifest=taxi_manifest,
            weather_manifest=weather_manifest,
        )

    # A previous run may have published a boundary month under a looser
    # coverage rule. Remove only deterministic outputs from the current scope.
    delete_keys(bucket, (analytics_output_key(period) for period in excluded))
    LOGGER.info("Analytics build finished for %s", list(publish_periods))


def main() -> None:
    setup_logging("build_analytics")
    run()


if __name__ == "__main__":
    main()
