import json
import logging

from botocore.exceptions import ClientError

from src.s3_io import s3


def load_manifest(bucket: str, key: str) -> dict:
    """
    Read manifest JSON from s3. 
    If the object does not exist (404), return {} 
    - first run ever is not an error. 
    Any other ClientError: raise
    """
    try:
        response  = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            logging.info("manifest not fount - starting fresh")
            return {}
        raise
    manifest = json.loads(response["Body"].read())
    logging.info("Manifest loaded: %d entries", len(manifest))
    return manifest

def save_manifest(
    manifest: dict,
    bucket: str,
    key: str
) -> None:
    """
    Write manifest dict to s3 as JSON.
    """
    s3.put_object(
        Body=json.dumps(
            manifest,
            indent=2,
            sort_keys=True
        ).encode("utf-8"),
        Bucket=bucket,
        Key=key
    )

def get_raw_etag(bucket: str, key: str) -> str:
    response = s3.head_object(Bucket=bucket, Key=key)
    return response["ETag"].strip('"')

def needs_processing(filename: str, raw_etag: str, manifest: dict) -> bool:
    entry = manifest.get(filename)

    if not entry:
        return True
        
    return entry.get("raw_etag") != raw_etag

