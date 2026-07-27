"""Clean raw NYC TLC files from S3 into partitioned processed, rejected
and quality outputs. Idempotent: deterministic output keys, re-runs overwrite."""
import argparse
import logging
import re
from pathlib import Path

import pandas as pd

from src.s3_io import download_file, list_keys, upload_df_overwrite, s3
from src.transform import create_quality_summary, transform_trips
from src.validate import validate_source

BUCKET = "jakub-nyc-taxi-lake-2026"
RAW_PREFIX = "raw/yellow_taxi/"
PROCESSED_PREFIX = "processed/yellow_taxi/"
REJECTED_PREFIX = "rejected/yellow_taxi/"
QUALITY_PREFIX = "reports/yellow_taxi/"

WORKDIR = Path("data/workdir")

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
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = parse_args()
    raw_keys = list_keys(BUCKET, RAW_PREFIX, suffix=".parquet")
    if args.only:
        raw_keys = [k for k in raw_keys if args.only in k]
    if not raw_keys:
        raise FileNotFoundError(f"No matching raw files in s3://{BUCKET}/{RAW_PREFIX}")
    for raw_key in raw_keys:
        process_key(raw_key)
    logging.info("Pipeline finished: %d file(s).", len(raw_keys))

# """Transform one raw NYC TLC file into processed and rejected outputs."""

# import argparse
# import logging
# import re
# from pathlib import Path

# import pandas as pd

# from src.transform import create_quality_summary, transform_trips
# from src.validate import validate_source


# PROJECT_DIR = Path(__file__).resolve().parent
# DEFAULT_INPUT = (
#     PROJECT_DIR
#     / "data/raw_download/yellow_tripdata_2024-01.parquet"
# )

# PROCESSED_DIR = PROJECT_DIR / "data/processed"
# REJECTED_DIR = PROJECT_DIR / "data/rejected"
# QUALITY_DIR = PROJECT_DIR / "data/quality"

# FILE_PATTERN = re.compile(
#     r"yellow_tripdata_(?P<year>\d{4})-(?P<month>\d{2})\.parquet"
# )


# def reporting_period(file_path: Path) -> tuple[int, int]:
#     match = FILE_PATTERN.fullmatch(file_path.name)

#     if match is None:
#         raise ValueError(
#             "Expected filename like "
#             "yellow_tripdata_2024-01.parquet, got: "
#             f"{file_path.name}"
#         )

#     return int(match["year"]), int(match["month"])


# def process_file(file_path: Path) -> None:
#     if not file_path.is_file():
#         raise FileNotFoundError(f"Source file not found: {file_path}")

#     year, month = reporting_period(file_path)

#     logging.info("Loading raw data from %s", file_path)
#     raw_df = pd.read_parquet(file_path)

#     validate_source(raw_df)

#     processed_df, rejected_df = transform_trips(
#         raw_df,
#         reporting_year=year,
#         reporting_month=month,
#         source_file=file_path.name,
#     )

#     quality_summary = create_quality_summary(
#         processed_df,
#         rejected_df,
#         raw_row_count=len(raw_df),
#     )

#     PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
#     REJECTED_DIR.mkdir(parents=True, exist_ok=True)
#     QUALITY_DIR.mkdir(parents=True, exist_ok=True)

#     output_name = file_path.stem
#     processed_path = (
#         PROCESSED_DIR / f"{output_name}_processed.parquet"
#     )
#     rejected_path = (
#         REJECTED_DIR / f"{output_name}_rejected.parquet"
#     )
#     quality_path = QUALITY_DIR / f"{output_name}_quality.csv"

#     processed_df.to_parquet(processed_path, index=False)
#     rejected_df.to_parquet(rejected_path, index=False)
#     quality_summary.to_csv(quality_path)

#     logging.info("Processed data saved to %s", processed_path)
#     logging.info("Rejected data saved to %s", rejected_path)
#     logging.info("Quality report saved to %s", quality_path)
#     logging.info("\n%s", quality_summary.to_string())


# def parse_args() -> argparse.Namespace:
#     parser = argparse.ArgumentParser(
#         description=(
#             "Clean one raw NYC Yellow Taxi parquet file. "
#             "The reporting period is read from its filename."
#         )
#     )
#     parser.add_argument(
#         "input_file",
#         nargs="?",
#         type=Path,
#         default=DEFAULT_INPUT,
#         help="Raw parquet file (defaults to January 2024).",
#     )

#     return parser.parse_args()


# if __name__ == "__main__":
#     logging.basicConfig(
#         level=logging.INFO,
#         format="%(asctime)s [%(levelname)s] %(message)s",
#     )

#     arguments = parse_args()
#     process_file(arguments.input_file.resolve())
