"""Download the configured immutable NYC TLC source files to the local cache."""

from src.config import MONTHS, RAW_DIR
from src.download import download_month
from src.logging_setup import setup_logging

BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
DATASET = "yellow_tripdata"


def main() -> None:
    setup_logging("download_raw")
    for month in MONTHS:
        download_month(month, base_url=BASE_URL, dataset=DATASET, raw_dir=RAW_DIR)


if __name__ == "__main__":
    main()
