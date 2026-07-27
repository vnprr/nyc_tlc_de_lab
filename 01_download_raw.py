from pathlib import Path
from src.download import download_month

# Data catalog
RAW_DIR = Path("data/raw_download")
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Config constants
BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
DATASET = "yellow_tripdata"
MONTHS = ["2024-01", "2024-02", "2024-03"]

if __name__ == "__main__":
    for month in MONTHS:
        download_month(month, base_url=BASE_URL, dataset=DATASET, raw_dir=RAW_DIR)