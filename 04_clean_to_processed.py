"""Clean configured raw taxi files into processed, rejected and quality data.

The temporary step assumes one writer.  Its manifest has two states:
``processing`` makes an interrupted run retry, while ``complete`` allows a
skip only when the input, transform version and physical outputs still match.
"""

import argparse
import logging
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.config import (
    MONTHS,
    PROCESSED_TAXI_PREFIX,
    QUALITY_TAXI_PREFIX,
    RAW_TAXI_PREFIX,
    REJECTED_TAXI_PREFIX,
    TAXI_MANIFEST_KEY,
    WORKDIR,
    parse_period,
    require_bucket,
)
from src.logging_setup import setup_logging
from src.manifest import (
    get_raw_etag,
    load_manifest,
    processing_reason,
    save_manifest,
)
from src.s3_io import (
    delete_keys,
    download_file,
    list_keys,
    upload_csv_overwrite,
    upload_df_overwrite,
)
from src.transform import TRANSFORM_VERSION, create_quality_summary, transform_trips
from src.validate import validate_source

LOGGER = logging.getLogger(__name__)
FILE_PATTERN = re.compile(r"yellow_tripdata_((?!0000)\d{4}-(?:0[1-9]|1[0-2]))\.parquet")


def source_period(filename: str) -> str:
    """Extract and validate the reporting period encoded in a TLC filename."""
    match = FILE_PATTERN.fullmatch(filename)
    if match is None:
        raise ValueError(f"Unexpected raw taxi filename: {filename}")
    return match.group(1)


def raw_key_for(period: str) -> str:
    parse_period(period)
    return f"{RAW_TAXI_PREFIX}yellow_tripdata_{period}.parquet"


def existing_output_keys(filename: str, *, bucket: str) -> set[str]:
    """Find outputs previously written for one source under managed prefixes."""
    source_period(filename)
    stem = Path(filename).stem
    keys = {
        f"{REJECTED_TAXI_PREFIX}{stem}.parquet",
        f"{QUALITY_TAXI_PREFIX}{stem}_quality.csv",
    }
    keys.update(list_keys(bucket, PROCESSED_TAXI_PREFIX, suffix=f"/{filename}"))
    return keys


def process_source(raw_key: str, *, bucket: str) -> tuple[dict, dict[str, int]]:
    """Run download, validation, transformation and publication for one file."""
    filename = Path(raw_key).name
    period = source_period(filename)
    year, month = parse_period(period)
    stem = Path(filename).stem

    WORKDIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORKDIR, prefix=f"clean-{period}-") as scratch:
        local_raw = Path(scratch) / filename
        download_file(bucket, raw_key, local_raw)
        raw = pd.read_parquet(local_raw)

        validate_source(raw, year, month)
        processed, rejected = transform_trips(
            raw,
            reporting_year=year,
            reporting_month=month,
            source_file=filename,
        )
        quality = create_quality_summary(processed, rejected, raw_row_count=len(raw))

        row_counts = {
            "raw": len(raw),
            "processed": len(processed),
            "rejected": len(rejected),
        }
        if row_counts["raw"] != row_counts["processed"] + row_counts["rejected"]:
            raise RuntimeError(f"Row-count reconciliation failed for {filename}")

        processed_outputs: dict[str, int] = {}
        partitioned = processed.assign(
            _year=processed["pickup_datetime"].dt.year,
            _month=processed["pickup_datetime"].dt.month,
        )
        for (event_year, event_month), frame in partitioned.groupby(["_year", "_month"], sort=True):
            key = (
                f"{PROCESSED_TAXI_PREFIX}year={int(event_year)}/"
                f"month={int(event_month):02d}/{filename}"
            )
            upload_df_overwrite(
                frame.drop(columns=["_year", "_month"]),
                bucket,
                key,
                WORKDIR,
            )
            processed_outputs[key] = len(frame)

        rejected_outputs: dict[str, int] = {}
        if not rejected.empty:
            key = f"{REJECTED_TAXI_PREFIX}{stem}.parquet"
            upload_df_overwrite(rejected, bucket, key, WORKDIR)
            rejected_outputs[key] = len(rejected)

        quality_key = f"{QUALITY_TAXI_PREFIX}{stem}_quality.csv"
        upload_csv_overwrite(quality.reset_index(), bucket, quality_key, WORKDIR)

    outputs = {
        "processed": dict(sorted(processed_outputs.items())),
        "rejected": dict(sorted(rejected_outputs.items())),
        "quality": quality_key,
    }
    return outputs, row_counts


def run(*, periods: tuple[str, ...], force: bool = False) -> None:
    """Process periods sequentially and checkpoint the manifest per source."""
    bucket = require_bucket()
    manifest = load_manifest(bucket, TAXI_MANIFEST_KEY)

    for period in periods:
        raw_key = raw_key_for(period)
        filename = Path(raw_key).name
        raw_etag = get_raw_etag(bucket, raw_key)
        reason = "forced"
        if not force:
            reason = processing_reason(
                filename,
                raw_etag,
                manifest,
                transform_version=TRANSFORM_VERSION,
                source_key=raw_key,
                bucket=bucket,
            )
        if not force and reason is None:
            LOGGER.info("SKIP %s (manifest and outputs are current)", filename)
            continue

        LOGGER.info("PROCESS %s (%s)", filename, reason)
        previous_outputs = existing_output_keys(filename, bucket=bucket)
        manifest[filename] = {
            "status": "processing",
            "source_key": raw_key,
            "raw_etag": raw_etag,
            "transform_version": TRANSFORM_VERSION,
            "started_at_utc": datetime.now(UTC).isoformat(),
        }
        save_manifest(manifest, bucket, TAXI_MANIFEST_KEY)

        outputs, row_counts = process_source(raw_key, bucket=bucket)
        output_keys = {
            *outputs["processed"],
            *outputs["rejected"],
            outputs["quality"],
        }

        stale_keys = previous_outputs - output_keys
        delete_keys(bucket, stale_keys)

        manifest[filename] = {
            "status": "complete",
            "source_key": raw_key,
            "raw_etag": raw_etag,
            "transform_version": TRANSFORM_VERSION,
            "processed_at_utc": datetime.now(UTC).isoformat(),
            "outputs": outputs,
            "row_counts": row_counts,
        }
        save_manifest(manifest, bucket, TAXI_MANIFEST_KEY)

    LOGGER.info("Taxi cleaning finished for %d source period(s)", len(periods))


def parse_month(value: str) -> str:
    try:
        parse_period(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        type=parse_month,
        help="Process exactly one YYYY-MM source instead of configured MONTHS.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    setup_logging("clean_taxi")
    args = parse_args()
    run(periods=(args.only,) if args.only else MONTHS, force=args.force)


if __name__ == "__main__":
    main()
