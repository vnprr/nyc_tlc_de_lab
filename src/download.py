import logging
import re
import tempfile
from pathlib import Path

import pyarrow.parquet as pq
import requests

LOGGER = logging.getLogger(__name__)
PARQUET_MAGIC = b"PAR1"


def has_parquet_envelope(path: Path) -> bool:
    """Check the lightweight Parquet signature at both ends of a file."""
    if not path.is_file() or path.stat().st_size < 8:
        return False
    with path.open("rb") as handle:
        header = handle.read(4)
        handle.seek(-4, 2)
        footer = handle.read(4)
    return header == PARQUET_MAGIC and footer == PARQUET_MAGIC


def is_readable_parquet(path: Path) -> bool:
    """Check the envelope and prove that a non-empty Parquet footer is readable."""
    if not has_parquet_envelope(path):
        return False
    try:
        metadata = pq.ParquetFile(path).metadata
    except Exception:  # PyArrow uses several parser-specific exception classes.
        return False
    return metadata.num_rows > 0 and metadata.num_columns > 0


def download_month(month: str, dataset: str, base_url: str, raw_dir: Path) -> Path:
    """
    Download the dataset for a specific month and save it to the raw data directory.

    Args:
        month (str): The month in 'YYYY-MM'
        dataset (str): The dataset name
        base_url (str): The base URL for the data
        raw_dir (Path): The directory to save the downloaded data
    """

    if re.fullmatch(r"(?!0000)\d{4}-(0[1-9]|1[0-2])", month) is None:
        raise ValueError(f"Invalid month {month!r}; expected YYYY-MM")
    if not dataset or "/" in dataset:
        raise ValueError("dataset must be a non-empty filename component")

    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{dataset}_{month}.parquet"
    url = f"{base_url.rstrip('/')}/{filename}"
    local_path = raw_dir / filename

    if is_readable_parquet(local_path):
        LOGGER.info("SKIP %s (readable non-empty local Parquet already exists)", filename)
        return local_path
    if local_path.exists():
        LOGGER.warning("Existing local file is incomplete or not Parquet; replacing %s", local_path)

    LOGGER.info("GET %s", url)
    # A fixed ``<filename>.part`` path lets two runs corrupt the same scratch
    # file.  Each download gets an isolated sibling and only the final replace
    # is atomic from the reader's point of view.
    with tempfile.NamedTemporaryFile(
        dir=raw_dir,
        prefix=f".{filename}.",
        suffix=".part",
        delete=False,
    ) as scratch:
        temp_file = Path(scratch.name)

    try:
        with requests.get(url=url, timeout=(10, 120), stream=True) as response:
            response.raise_for_status()
            expected_size_header = response.headers.get("Content-Length")
            expected_size = int(expected_size_header) if expected_size_header else None

            downloaded_size = 0
            with temp_file.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded_size += len(chunk)

        if downloaded_size == 0:
            raise OSError(f"Downloaded an empty response from {url}")
        if expected_size is not None and downloaded_size != expected_size:
            raise OSError(
                f"Incomplete download from {url}: expected {expected_size} bytes, "
                f"received {downloaded_size}"
            )
        if not is_readable_parquet(temp_file):
            raise ValueError(f"Response from {url} is not a readable non-empty Parquet file")

        temp_file.replace(local_path)
    except Exception:
        temp_file.unlink(missing_ok=True)
        raise

    size = local_path.stat().st_size / 1024 / 1024
    LOGGER.info("OK %s (%.2f MB)", local_path, size)

    return local_path
