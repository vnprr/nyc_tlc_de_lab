from src.config import RAW_DIR
from src.download import download_month
from src.logging_setup import setup_logging

from src.config import MONTHS

# Data catalog
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Config constants
BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
DATASET = "yellow_tripdata"

if __name__ == "__main__":
    setup_logging("download_raw")
    for month in MONTHS:
        download_month(month, base_url=BASE_URL, dataset=DATASET, raw_dir=RAW_DIR)
