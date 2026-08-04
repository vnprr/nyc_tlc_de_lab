"""Run a quick smoke check of one source file without opening Jupyter."""

import argparse
import logging
from pathlib import Path

import pandas as pd

from src.config import MONTHS, RAW_DIR
from src.logging_setup import setup_logging
from src.validate import validate_source

LOGGER = logging.getLogger(__name__)


def load_source(file_path: Path) -> pd.DataFrame:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_size = file_path.stat().st_size
    if file_size == 0:
        raise ValueError(f"File is empty: {file_path}")

    file_size_mb = file_size / (1024 * 1024)
    LOGGER.info("Source file found: %s", file_path)
    LOGGER.info("File size: %.2f MB", file_size_mb)
    LOGGER.info("Loading source data from: %s", file_path)
    return pd.read_parquet(file_path)


def log_basic_info(df: pd.DataFrame) -> None:
    LOGGER.info("DataFrame loaded")
    LOGGER.info("Rows: %s", f"{len(df):,}")
    LOGGER.info("Columns: %s", len(df.columns))
    LOGGER.info("Column names: %s", list(df.columns))

    missing = df.isna().sum()
    if missing.any():
        LOGGER.info(
            "Missing values:\n%s",
            missing[missing > 0].sort_values(ascending=False),
        )
    else:
        LOGGER.info("No missing values found")

    duplicate_rows = int(df.duplicated(keep=False).sum())
    LOGGER.info("Rows belonging to exact duplicate groups: %s", duplicate_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--month",
        choices=MONTHS,
        default=MONTHS[0],
        help="Configured source month to profile.",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging("profile_source")
    args = parse_args()
    year, month = map(int, args.month.split("-"))
    data_file = RAW_DIR / f"yellow_tripdata_{args.month}.parquet"
    source = load_source(data_file)
    log_basic_info(source)
    validate_source(source, reporting_year=year, reporting_month=month)


if __name__ == "__main__":
    main()
