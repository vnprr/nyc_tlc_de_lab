from src.config import BUCKET, RAW_DIR, RAW_TAXI_PREFIX
from src.logging_setup import setup_logging
from src.s3_io import upload_file_skip_existing

if __name__ == "__main__":
    setup_logging("upload_raw")
    files = sorted(RAW_DIR.glob("yellow_tripdata_*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files in {RAW_DIR}")
    for f in files:
        upload_file_skip_existing(f, BUCKET, RAW_TAXI_PREFIX + f.name)