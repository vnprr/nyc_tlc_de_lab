"""Small contract tests for the incremental taxi manifest."""

import json
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src import manifest
from src.transform import TRANSFORM_VERSION

BUCKET = "test-bucket"
KEY = "state/manifest.json"
FILENAME = "yellow_tripdata_2024-01.parquet"
SOURCE_KEY = f"raw/yellow_taxi/{FILENAME}"
PROCESSED_KEY = f"processed/yellow_taxi/year=2024/month=01/{FILENAME}"
QUALITY_KEY = "reports/yellow_taxi/yellow_tripdata_2024-01_quality.csv"


def client_error(code: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "test error"},
            "ResponseMetadata": {"HTTPStatusCode": 500},
        },
        "get_object",
    )


def complete_entry(**updates) -> dict:
    entry = {
        "status": "complete",
        "source_key": SOURCE_KEY,
        "raw_etag": "e1",
        "transform_version": TRANSFORM_VERSION,
        "processed_at_utc": "2026-08-02T12:00:00+00:00",
        "outputs": {
            "processed": {PROCESSED_KEY: 9},
            "rejected": {},
            "quality": QUALITY_KEY,
        },
        "row_counts": {"raw": 9, "processed": 9, "rejected": 0},
    }
    entry.update(updates)
    return entry


def test_load_manifest_returns_decoded_json(monkeypatch):
    body = MagicMock()
    body.read.return_value = b'{"b.parquet": {"raw_etag": "e2"}}'
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": body}
    monkeypatch.setattr(manifest, "s3", s3)

    result = manifest.load_manifest(BUCKET, KEY)

    assert result == {"b.parquet": {"raw_etag": "e2"}}
    s3.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY)


@pytest.mark.parametrize("code", ["404", "NoSuchKey"])
def test_load_manifest_returns_empty_dict_when_object_is_missing(monkeypatch, code):
    s3 = MagicMock()
    s3.get_object.side_effect = client_error(code)
    monkeypatch.setattr(manifest, "s3", s3)

    assert manifest.load_manifest(BUCKET, KEY) == {}


def test_load_manifest_reraises_unrecognized_client_error(monkeypatch):
    s3 = MagicMock()
    error = client_error("AccessDenied")
    s3.get_object.side_effect = error
    monkeypatch.setattr(manifest, "s3", s3)

    with pytest.raises(ClientError) as raised:
        manifest.load_manifest(BUCKET, KEY)

    assert raised.value is error


def test_save_manifest_serializes_deterministically_and_uploads_bytes(monkeypatch):
    s3 = MagicMock()
    monkeypatch.setattr(manifest, "s3", s3)
    value = {"z": {"raw_etag": "e2"}, "a": {"raw_etag": "e1"}}

    manifest.save_manifest(value, BUCKET, KEY)

    s3.put_object.assert_called_once_with(
        Bucket=BUCKET,
        Key=KEY,
        Body=json.dumps(value, indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )


def test_get_raw_etag_returns_etag_without_quotes(monkeypatch):
    s3 = MagicMock()
    s3.head_object.return_value = {"ETag": '"abc123"'}
    monkeypatch.setattr(manifest, "s3", s3)

    assert manifest.get_raw_etag(BUCKET, "raw/input.parquet") == "abc123"


def test_get_raw_etag_propagates_s3_error(monkeypatch):
    s3 = MagicMock()
    error = client_error("404")
    s3.head_object.side_effect = error
    monkeypatch.setattr(manifest, "s3", s3)

    with pytest.raises(ClientError) as raised:
        manifest.get_raw_etag(BUCKET, "raw/missing.parquet")

    assert raised.value is error


def test_needs_processing_returns_true_for_new_file():
    assert manifest.needs_processing(FILENAME, "e1", {}) is True


def test_needs_processing_returns_false_for_unchanged_file():
    state = {FILENAME: complete_entry()}

    assert manifest.needs_processing(FILENAME, "e1", state) is False


def test_needs_processing_returns_true_for_changed_etag():
    state = {FILENAME: complete_entry()}

    assert manifest.needs_processing(FILENAME, "e2", state) is True


def test_needs_processing_returns_true_when_entry_has_no_etag():
    entry = complete_entry()
    del entry["raw_etag"]

    assert manifest.needs_processing(FILENAME, "e1", {FILENAME: entry}) is True


def test_changed_transform_version_forces_processing():
    state = {FILENAME: complete_entry(transform_version="older")}

    assert (
        manifest.processing_reason(
            FILENAME,
            "e1",
            state,
            transform_version=TRANSFORM_VERSION,
        )
        == "transform_version_changed"
    )


def test_missing_physical_output_forces_processing():
    state = {FILENAME: complete_entry()}

    reason = manifest.processing_reason(
        FILENAME,
        "e1",
        state,
        bucket=BUCKET,
        output_exists=lambda _bucket, key: key != QUALITY_KEY,
    )

    assert reason == f"missing_output:{QUALITY_KEY}"


def test_inconsistent_row_counts_invalidate_complete_entry():
    entry = complete_entry(row_counts={"raw": 10, "processed": 9, "rejected": 0})

    assert manifest.processing_reason(FILENAME, "e1", {FILENAME: entry}) == (
        "row_count_reconciliation"
    )


def test_quality_only_entry_cannot_hide_missing_processed_output():
    entry = complete_entry(outputs={"processed": {}, "rejected": {}, "quality": QUALITY_KEY})

    assert manifest.processing_reason(FILENAME, "e1", {FILENAME: entry}) == (
        "output_row_count_reconciliation"
    )


def test_processed_output_counts_must_sum_to_manifest_total():
    entry = complete_entry(
        outputs={
            "processed": {PROCESSED_KEY: 8},
            "rejected": {},
            "quality": QUALITY_KEY,
        }
    )

    assert manifest.processing_reason(FILENAME, "e1", {FILENAME: entry}) == (
        "output_row_count_reconciliation"
    )


def test_raw_key_cannot_masquerade_as_processed_output():
    entry = complete_entry(
        outputs={
            "processed": {SOURCE_KEY: 9},
            "rejected": {},
            "quality": QUALITY_KEY,
        }
    )

    assert manifest.processing_reason(FILENAME, "e1", {FILENAME: entry}) == (
        "output_row_count_reconciliation"
    )
