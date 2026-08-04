"""Small S3 manifest used by the incremental taxi step.

The project has one writer.  The manifest therefore solves recovery after a
failed run, not distributed locking.  A source is current only when its input,
transform version, row counts and declared outputs still agree.
"""

import json
import logging
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from src.config import PROCESSED_TAXI_PREFIX, QUALITY_TAXI_PREFIX, REJECTED_TAXI_PREFIX
from src.s3_io import object_exists, s3

Manifest = dict[str, dict[str, Any]]
ROW_COUNT_FIELDS = {"raw", "processed", "rejected"}


def load_manifest(bucket: str, key: str) -> Manifest:
    """Read a JSON manifest, returning an empty one on the first run."""
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
            logging.info("Manifest not found; starting with an empty manifest")
            return {}
        raise

    manifest = json.loads(response["Body"].read())
    if not isinstance(manifest, dict):
        raise ValueError("Manifest root must be a JSON object")
    logging.info("Manifest loaded: %d entries", len(manifest))
    return manifest


def save_manifest(manifest: Mapping[str, Any], bucket: str, key: str) -> None:
    """Write deterministic UTF-8 JSON to S3."""
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )


def get_raw_etag(bucket: str, key: str) -> str:
    """Return an S3 ETag without surrounding quotes."""
    return s3.head_object(Bucket=bucket, Key=key)["ETag"].strip('"')


def _validated_output_keys(
    filename: str,
    entry: Mapping[str, Any],
) -> tuple[str, ...] | None:
    outputs = entry.get("outputs")
    counts = entry.get("row_counts")
    if not isinstance(outputs, Mapping) or not isinstance(counts, Mapping):
        return None
    if set(outputs) != {"processed", "rejected", "quality"}:
        return None

    processed = outputs["processed"]
    rejected = outputs["rejected"]
    quality = outputs["quality"]
    if not isinstance(processed, Mapping) or not isinstance(rejected, Mapping):
        return None
    if not isinstance(quality, str) or not quality or len(rejected) > 1:
        return None

    data_outputs = {**processed, **rejected}
    if len(data_outputs) != len(processed) + len(rejected):
        return None
    if any(
        not isinstance(key, str)
        or not key
        or isinstance(rows, bool)
        or not isinstance(rows, int)
        or rows <= 0
        for key, rows in data_outputs.items()
    ):
        return None
    if quality in data_outputs:
        return None
    processed_pattern = re.compile(
        rf"{re.escape(PROCESSED_TAXI_PREFIX)}"
        rf"year=(?!0000)\d{{4}}/month=(?:0[1-9]|1[0-2])/{re.escape(filename)}"
    )
    if any(processed_pattern.fullmatch(key) is None for key in processed):
        return None
    stem = Path(filename).stem
    expected_rejected = f"{REJECTED_TAXI_PREFIX}{stem}.parquet"
    if any(key != expected_rejected for key in rejected):
        return None
    if quality != f"{QUALITY_TAXI_PREFIX}{stem}_quality.csv":
        return None
    if sum(processed.values()) != counts.get("processed"):
        return None
    if sum(rejected.values()) != counts.get("rejected"):
        return None
    return (*processed, *rejected, quality)


def manifest_output_keys(
    filename: str,
    entry: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Return declared output keys or an empty tuple for malformed state."""
    if not isinstance(entry, Mapping):
        return ()
    return _validated_output_keys(filename, entry) or ()


def _row_counts_are_consistent(entry: Mapping[str, Any]) -> bool:
    counts = entry.get("row_counts")
    if not isinstance(counts, Mapping) or set(counts) != ROW_COUNT_FIELDS:
        return False
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        return False
    return counts["raw"] > 0 and counts["raw"] == counts["processed"] + counts["rejected"]


def processing_reason(
    filename: str,
    raw_etag: str,
    manifest: Mapping[str, Any],
    *,
    transform_version: str | None = None,
    source_key: str | None = None,
    bucket: str | None = None,
    output_exists: Callable[[str, str], bool] = object_exists,
) -> str | None:
    """Return why a source must run, or ``None`` when it can be skipped."""
    entry = manifest.get(filename)
    if not isinstance(entry, Mapping):
        return "missing_manifest_entry"
    if entry.get("status") != "complete":
        return f"manifest_status:{entry.get('status', 'missing')}"
    if source_key is not None and entry.get("source_key") != source_key:
        return "source_key_changed"
    if entry.get("raw_etag") != raw_etag:
        return "raw_etag_changed"
    if transform_version is not None and entry.get("transform_version") != transform_version:
        return "transform_version_changed"
    if not _row_counts_are_consistent(entry):
        return "row_count_reconciliation"

    output_keys = _validated_output_keys(filename, entry)
    if output_keys is None:
        return "output_row_count_reconciliation"
    if bucket is not None:
        for key in output_keys:
            if not output_exists(bucket, key):
                return f"missing_output:{key}"
    return None


def needs_processing(
    filename: str,
    raw_etag: str,
    manifest: Mapping[str, Any],
    **kwargs: Any,
) -> bool:
    """Compatibility wrapper used by the original small unit tests."""
    return processing_reason(filename, raw_etag, manifest, **kwargs) is not None
