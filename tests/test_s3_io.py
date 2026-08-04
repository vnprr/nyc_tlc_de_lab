import io
from unittest.mock import MagicMock

import pytest

from src import s3_io


def test_existing_object_with_different_sha256_is_not_overwritten(tmp_path, monkeypatch):
    local = tmp_path / "raw.parquet"
    local.write_bytes(b"local content")
    s3 = MagicMock()
    s3.head_object.return_value = {
        "ContentLength": local.stat().st_size,
        "Metadata": {"sha256": "0" * 64},
    }
    monkeypatch.setattr(s3_io, "s3", s3)

    with pytest.raises(s3_io.RawObjectCollisionError, match="SHA-256 differs"):
        s3_io.upload_file_skip_existing(local, "bucket", "raw/file")

    s3.upload_file.assert_not_called()


def test_legacy_object_same_size_but_different_content_is_detected(tmp_path, monkeypatch):
    local = tmp_path / "raw.parquet"
    local.write_bytes(b"local!")
    s3 = MagicMock()
    s3.head_object.return_value = {
        "ContentLength": local.stat().st_size,
        "Metadata": {},
    }
    s3.get_object.return_value = {"Body": io.BytesIO(b"remote")}
    monkeypatch.setattr(s3_io, "s3", s3)

    with pytest.raises(s3_io.RawObjectCollisionError, match="SHA-256 differs"):
        s3_io.upload_file_skip_existing(local, "bucket", "raw/file")
