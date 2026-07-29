from src.s3_io import object_exists
import logging
import boto3
from botocore.exceptions import ClientError
import json

s3 = boto3.client("s3")

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
    Read manifest JSON from s3. 
    If the object does not exist (404), 
    return {} - first run ever is not an error. 
    Any other ClientError: raise
    """
    try:
        response = s3.put_object(
            body = json.dumps(
                    manifest, 
                    intent = 2,
                    sort_keys=True,
                    default=str
                ).encode("utf-8"),
            Bucket = bucket,
            Key = key
        )
    except Exception as e:
        logging.error("save_manifest error:", e)
        raise

def get_raw_etag(bucket: str, key: str) -> str:
    # try:
    response = s3.head_object(Bucket=bucket, Key=key)
    return response["ETag"].strip('"')
    # except Exception as e:
    #     logging.error("get_raw_etag error:", e)
    #     raise

def needs_processing(filename: str, raw_etag: str, manifest: dict) -> bool:
    entry = manifest.get(filename)

    if not entry:
        return True
        
    return entry.get("raw_etag") != raw_etag

# if __name__ == "__main__":
def main():
    
    # print("needs_processing tests:")
    # assert needs_processing("a.parquet", "e1", {}) is True
    # assert needs_processing("a.parquet", "e1", {"a.parquet": {"raw_etag": "e1"}}) is True
    # assert needs_processing("a.parquet", "e1", {"a.parquet": {"raw_etag": "e1"}}) is False
    # assert needs_processing("a.parquet", "e1", {"a.parquet": {}}) is True

    out = load_manifest("jakub-nyc-taxi-lake-2026" , "mnnmn" )
    print(out)
    