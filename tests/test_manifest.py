"""Unit tests for src.manifest without real AWS calls."""

import json
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from src import manifest


BUCKET = "test-bucket"
KEY = "state/manifest.json"


def client_error(code: str) -> ClientError:
    """Build a boto-style ClientError with the given S3 error code."""
    return ClientError(
        {
            "Error": {"Code": code, "Message": "test error"},
            "ResponseMetadata": {"HTTPStatusCode": 500},
        },
        "get_object",
    )


def test_load_manifest_returns_decoded_json(monkeypatch):
    """Returns dict when manifest object exists and contains valid JSON."""
    body = MagicMock()
    body.read.return_value = b'{"b.parquet": {"raw_etag": "e2"}}'
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": body}
    monkeypatch.setattr(manifest, "s3", s3)

    result = manifest.load_manifest(BUCKET, KEY)

    assert result == {"b.parquet": {"raw_etag": "e2"}}
    s3.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY)
    body.read.assert_called_once_with()


@pytest.mark.parametrize("code", ["404", "NoSuchKey"])
def test_load_manifest_returns_empty_dict_when_object_is_missing(monkeypatch, code):
    """Returns empty dict when S3 reports missing manifest object."""
    s3 = MagicMock()
    s3.get_object.side_effect = client_error(code)
    monkeypatch.setattr(manifest, "s3", s3)

    result = manifest.load_manifest(BUCKET, KEY)

    assert result == {}
    s3.get_object.assert_called_once_with(Bucket=BUCKET, Key=KEY)


def test_load_manifest_reraises_unrecognized_client_error(monkeypatch):
    """Re-raises unexpected S3 errors instead of swallowing them."""
    s3 = MagicMock()
    error = client_error("AccessDenied")
    s3.get_object.side_effect = error
    monkeypatch.setattr(manifest, "s3", s3)

    with pytest.raises(ClientError) as raised:
        manifest.load_manifest(BUCKET, KEY)

    assert raised.value is error


def test_save_manifest_serializes_deterministically_and_uploads_bytes(monkeypatch):
    """Uploads UTF-8 JSON bytes using deterministic key order and indentation."""
    s3 = MagicMock()
    monkeypatch.setattr(manifest, "s3", s3)
    value = {
        "z.parquet": {"name": "zolc", "raw_etag": "e2"},
        "a.parquet": {"raw_etag": "e1"},
    }

    result = manifest.save_manifest(value, BUCKET, KEY)

    expected = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
    assert result is None
    s3.put_object.assert_called_once_with(Bucket=BUCKET, Key=KEY, Body=expected)


def test_get_raw_etag_returns_etag_without_quotes(monkeypatch):
    """Normalizes quoted S3 ETag by stripping surrounding quotes."""
    s3 = MagicMock()
    s3.head_object.return_value = {"ETag": '"abc123"'}
    monkeypatch.setattr(manifest, "s3", s3)

    result = manifest.get_raw_etag(BUCKET, "raw/input.parquet")

    assert result == "abc123"
    s3.head_object.assert_called_once_with(Bucket=BUCKET, Key="raw/input.parquet")
    s3.get_object.assert_not_called()


def test_get_raw_etag_propagates_s3_error(monkeypatch):
    """Propagates S3 errors from head_object without custom handling."""
    s3 = MagicMock()
    error = client_error("404")
    s3.head_object.side_effect = error
    monkeypatch.setattr(manifest, "s3", s3)

    with pytest.raises(ClientError) as raised:
        manifest.get_raw_etag(BUCKET, "raw/missing.parquet")

    assert raised.value is error


def test_needs_processing_returns_true_for_new_file():
    """Returns True when file has no entry in manifest."""
    assert manifest.needs_processing("a.parquet", "e1", {}) is True


def test_needs_processing_returns_false_for_unchanged_file():
    """Returns False when stored and current ETag values are equal."""
    state = {"a.parquet": {"raw_etag": "e1"}}

    assert manifest.needs_processing("a.parquet", "e1", state) is False


def test_needs_processing_returns_true_for_changed_etag():
    """Returns True when stored and current ETag values differ."""
    state = {"a.parquet": {"raw_etag": "e1"}}

    assert manifest.needs_processing("a.parquet", "e2", state) is True


def test_needs_processing_returns_true_when_entry_has_no_etag():
    """Returns True when entry exists but raw_etag field is missing."""
    state = {"a.parquet": {}}

    assert manifest.needs_processing("a.parquet", "e1", state) is True
