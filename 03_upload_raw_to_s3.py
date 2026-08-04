"""Upload only the configured, complete taxi source files to immutable S3 keys."""

from pathlib import Path

from src.config import MONTHS, RAW_DIR, RAW_TAXI_PREFIX, require_bucket
from src.download import is_readable_parquet
from src.logging_setup import setup_logging
from src.s3_io import upload_file_skip_existing


def configured_source_files() -> tuple[Path, ...]:
    """Resolve the exact local inputs for the configured reporting scope."""
    files = tuple(RAW_DIR / f"yellow_tripdata_{month}.parquet" for month in MONTHS)
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing configured taxi source files: {missing}")

    invalid = [str(path) for path in files if not is_readable_parquet(path)]
    if invalid:
        raise ValueError(f"Unreadable, empty or non-Parquet taxi source files: {invalid}")
    return files


def main() -> None:
    setup_logging("upload_raw")
    bucket = require_bucket()
    for source_file in configured_source_files():
        upload_file_skip_existing(
            source_file,
            bucket,
            RAW_TAXI_PREFIX + source_file.name,
        )


if __name__ == "__main__":
    main()
