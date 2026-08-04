"""Small S3 helpers shared by the temporary pipeline entrypoints."""

import hashlib
import logging
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
MISSING_CODES = {"404", "NoSuchKey", "NotFound"}


class RawObjectCollisionError(RuntimeError):
    """An immutable raw key already contains different bytes."""


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_sha256(body: Any, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    try:
        while chunk := body.read(chunk_size):
            digest.update(chunk)
    finally:
        if hasattr(body, "close"):
            body.close()
    return digest.hexdigest()


def object_exists(bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] in MISSING_CODES:
            return False
        raise


def list_keys(bucket: str, prefix: str, suffix: str = "") -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(
            item["Key"] for item in page.get("Contents", []) if item["Key"].endswith(suffix)
        )
    return sorted(keys)


def download_file(bucket: str, key: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, key, str(local_path))


def _verify_existing_raw(
    local_path: Path,
    bucket: str,
    key: str,
    local_sha256: str,
    remote: dict[str, Any],
) -> None:
    if remote.get("ContentLength") != local_path.stat().st_size:
        raise RawObjectCollisionError(
            f"Raw key collision for s3://{bucket}/{key}: file sizes differ"
        )

    metadata = {str(name).lower(): str(value) for name, value in remote.get("Metadata", {}).items()}
    remote_sha256 = metadata.get("sha256")
    if remote_sha256 is None:
        remote_sha256 = _stream_sha256(s3.get_object(Bucket=bucket, Key=key)["Body"])

    if remote_sha256.lower() != local_sha256:
        raise RawObjectCollisionError(f"Raw key collision for s3://{bucket}/{key}: SHA-256 differs")


def upload_file_skip_existing(local_path: Path, bucket: str, key: str) -> bool:
    """Upload immutable raw data or verify that existing bytes are identical.

    The project currently has a single-writer contract, so this function does
    not implement locking or conditional writes.
    """
    local_sha256 = file_sha256(local_path)
    try:
        remote = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response["Error"]["Code"] not in MISSING_CODES:
            raise
    else:
        _verify_existing_raw(local_path, bucket, key, local_sha256, remote)
        logging.info("SKIP s3://%s/%s (identical SHA-256)", bucket, key)
        return False

    s3.upload_file(
        str(local_path),
        bucket,
        key,
        ExtraArgs={"Metadata": {"sha256": local_sha256}},
    )
    logging.info("UPLOAD s3://%s/%s", bucket, key)
    return True


def upload_df_overwrite(
    df: pd.DataFrame,
    bucket: str,
    key: str,
    workdir: Path,
    *,
    metadata: Mapping[str, str] | None = None,
) -> None:
    """Serialize a derived DataFrame in an isolated directory and upload it."""
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workdir, prefix="upload-") as scratch:
        local_path = Path(scratch) / (Path(key).name or "data.parquet")
        df.to_parquet(local_path, index=False)
        if metadata is None:
            s3.upload_file(str(local_path), bucket, key)
        else:
            s3.upload_file(
                str(local_path),
                bucket,
                key,
                ExtraArgs={"Metadata": dict(metadata)},
            )
    logging.info("WRITE s3://%s/%s (%s rows)", bucket, key, f"{len(df):,}")


def upload_csv_overwrite(
    df: pd.DataFrame,
    bucket: str,
    key: str,
    workdir: Path,
) -> None:
    """Write a derived CSV without a synthetic DataFrame index column."""
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workdir, prefix="upload-") as scratch:
        local_path = Path(scratch) / (Path(key).name or "data.csv")
        df.to_csv(local_path, index=False)
        s3.upload_file(str(local_path), bucket, key)
    logging.info("WRITE s3://%s/%s (%s rows)", bucket, key, f"{len(df):,}")


def delete_keys(bucket: str, keys: Iterable[str]) -> None:
    """Delete only exact keys selected by the caller."""
    for key in sorted(set(keys)):
        if not key:
            raise ValueError("Refusing to delete an empty S3 key")
        s3.delete_object(Bucket=bucket, Key=key)
        logging.info("DELETE s3://%s/%s", bucket, key)
