from pathlib import Path
import boto3
from botocore.exceptions import ClientError

BUCKET = "jakub-nyc-taxi-lake-2026"
RAW_PREFIX = "raw/yellow_taxi/"
RAW_DIR = Path("data/raw_download")

s3 = boto3.client("s3")

def object_exists(bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise

def upload_raw_file(local_path: Path) -> None:
    key = RAW_PREFIX + local_path.name
    if object_exists(BUCKET, key):
        print(f"SKIP: s3://{BUCKET}/{key} (already in raw!)")
        return
    print(f"UPLOAD: {local_path.name}")
    s3.upload_file(str(local_path), BUCKET, key)
    print(f"OK: s3://{BUCKET}/{key}")

if __name__ == "__main__":
    files = sorted(RAW_DIR.glob("yellow_tripdata_*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files in {RAW_DIR}")
    for f in files:
        upload_raw_file(f)