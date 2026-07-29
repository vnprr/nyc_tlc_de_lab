"""Clean raw NYC TLC files from S3 into partitioned processed, rejected
and quality outputs. Idempotent: deterministic output keys, re-runs overwrite."""

import argparse
from datetime import datetime, timezone
import logging
import pandas as pd
from pathlib import Path
import re

from src.manifest import get_raw_etag, load_manifest, needs_processing, save_manifest
from src.s3_io import download_file, list_keys, upload_df_overwrite, s3
from src.transform import create_quality_summary, transform_trips
from src.validate import validate_source

# variables from env file: 
from src.config import (
    BUCKET, WORKDIR,
    RAW_TAXI_PREFIX, PROCESSED_TAXI_PREFIX,
    REJECTED_TAXI_PREFIX, QUALITY_TAXI_PREFIX,
    TAXI_MANIFEST_KEY,
)



PROCESSED_PREFIX = "processed/yellow_taxi/"
REJECTED_PREFIX = "rejected/yellow_taxi/"
QUALITY_PREFIX = "reports/yellow_taxi/"



FILE_PATTERN = re.compile(
    r"yellow_tripdata_(?P<year>\d{4})-(?P<month>\d{2})\.parquet"
)


def reporting_period(filename: str) -> tuple[int, int]:
    match = FILE_PATTERN.fullmatch(filename)
    if match is None:
        raise ValueError(f"Unexpected raw file name: {filename}")
    return int(match["year"]), int(match["month"])


def process_key(raw_key: str) -> None:
    filename = Path(raw_key).name
    stem = Path(raw_key).stem
    year, month = reporting_period(filename)

    local_raw = WORKDIR / filename
    logging.info("=== %s ===", filename)
    download_file(BUCKET, raw_key, local_raw)
    raw_df = pd.read_parquet(local_raw)

    validate_source(raw_df)
    processed_df, rejected_df = transform_trips(
        raw_df,
        reporting_year=year,
        reporting_month=month,
        source_file=filename,
    )
    quality_summary = create_quality_summary(
        processed_df, rejected_df, raw_row_count=len(raw_df),
    )

    # processed: hive partitions by validated event date; file named after source
    partition = processed_df.assign(
        year=processed_df["pickup_datetime"].dt.year,
        month=processed_df["pickup_datetime"].dt.month,
    )
    for (part_year, part_month), part_df in partition.groupby(["year", "month"]):
        key = (f"{PROCESSED_PREFIX}year={part_year}/month={part_month:02d}/"
               f"{stem}.parquet")
        upload_df_overwrite(
            part_df.drop(columns=["year", "month"]), BUCKET, key, WORKDIR,
        )

    if len(rejected_df) > 0:
        upload_df_overwrite(
            rejected_df, BUCKET, f"{REJECTED_PREFIX}{stem}.parquet", WORKDIR,
        )

    quality_local = WORKDIR / f"{stem}_quality.csv"
    quality_summary.to_csv(quality_local)
    s3.upload_file(
        str(quality_local), BUCKET, f"{QUALITY_PREFIX}{stem}_quality.csv",
    )
    logging.info("REPORT s3://%s/%s%s_quality.csv", BUCKET, QUALITY_PREFIX, stem)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", default=None,
        help="Process a single month, e.g. 2024-01 (default: all raw files).",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = parse_args()
    raw_keys = list_keys(BUCKET, RAW_TAXI_PREFIX, suffix=".parquet")
    if args.only:
        raw_keys = [k for k in raw_keys if args.only in k]
    if not raw_keys:
        raise FileNotFoundError(f"No matching raw files in s3://{BUCKET}/{RAW_TAXI_PREFIX}")
    manifest = load_manifest(BUCKET, TAXI_MANIFEST_KEY)
    for raw_key in raw_keys:
        filename = Path(raw_key).name
        etag = get_raw_etag(BUCKET, raw_key)
        if not args.force and not needs_processing(filename, etag, manifest):
            logging.info("SKIP %s (manifest)", filename)
            continue
        process_key(raw_key)
        manifest[filename] = {
            "raw_etag": etag,
            "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        save_manifest(manifest, BUCKET, TAXI_MANIFEST_KEY)
    logging.info("Pipeline finished: %d file(s).", len(raw_keys))
