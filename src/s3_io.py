"""S3 helpers shared by pipeline scripts."""
import logging
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import ClientError

s3 = boto3.client("s3")


def object_exists(bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


def list_keys(bucket: str, prefix: str, suffix: str = "") -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            if item["Key"].endswith(suffix):
                keys.append(item["Key"])
    return sorted(keys)


def download_file(bucket: str, key: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, key, str(local_path))


def upload_file_skip_existing(local_path: Path, bucket: str, key: str) -> bool:
    """Raw-zone strategy: immutable, skip if present. Returns True if uploaded."""
    if object_exists(bucket, key):
        logging.info("SKIP s3://%s/%s (already exists)", bucket, key)
        return False
    s3.upload_file(str(local_path), bucket, key)
    logging.info("UPLOAD s3://%s/%s", bucket, key)
    return True


def upload_df_overwrite(df: pd.DataFrame, bucket: str, key: str,
                        workdir: Path) -> None:
    """Derived-zone strategy: deterministic key, always overwrite."""
    local = workdir / Path(key).name
    local.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(local, index=False)
    s3.upload_file(str(local), bucket, key)
    logging.info("WRITE s3://%s/%s (%s rows)", bucket, key, f"{len(df):,}")