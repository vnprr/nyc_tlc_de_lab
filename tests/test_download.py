import io

import pandas as pd
import pytest

from src import download


def parquet_bytes() -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame({"value": [1]}).to_parquet(buffer, index=False)
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, body: bytes, content_length: int) -> None:
        self.body = body
        self.headers = {"Content-Length": str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self.body


def test_incomplete_download_does_not_replace_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "yellow_tripdata_2024-01.parquet"
    target.write_bytes(b"existing damaged file")
    body = parquet_bytes()
    response = FakeResponse(body, content_length=len(body) + 1)
    monkeypatch.setattr(download.requests, "get", lambda **_kwargs: response)

    with pytest.raises(OSError, match="Incomplete download"):
        download.download_month("2024-01", "yellow_tripdata", "https://example.test", tmp_path)

    assert target.read_bytes() == b"existing damaged file"


def test_fake_parquet_envelope_is_rejected(tmp_path, monkeypatch):
    body = b"PAR1not-a-real-parquetPAR1"
    response = FakeResponse(body, content_length=len(body))
    monkeypatch.setattr(download.requests, "get", lambda **_kwargs: response)

    with pytest.raises(ValueError, match="readable non-empty Parquet"):
        download.download_month("2024-01", "yellow_tripdata", "https://example.test", tmp_path)
