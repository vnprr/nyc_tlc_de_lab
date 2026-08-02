import logging
from pathlib import Path

import requests


def download_month(month: str, dataset: str, base_url: str, raw_dir: Path) -> Path:
    """
    Download the dataset for a specific month and save it to the raw data directory.

    Args:
        month (str): The month in 'YYYY-MM'
        dataset (str): The dataset name
        base_url (str): The base URL for the data
        raw_dir (Path): The directory to save the downloaded data
    """

    filename = f"{dataset}_{month}.parquet"
    url = f"{base_url}/{filename}"
    local_path = raw_dir / filename

    if local_path.exists():
        logging.info("SKIP %s (already downloaded)", filename)
        return local_path

    logging.info("GET %s", url)

    response = requests.get(url=url, timeout=60, stream=True)

    response.raise_for_status()  # Raise an error for bad responses

    temp_file = local_path.with_suffix(
        ".tmp"
    )  # Create a temporary file to avoid partial downloads

    with open(temp_file, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1 MB chunks
            f.write(chunk)

    temp_file.rename(local_path)

    size = local_path.stat().st_size / 1024 / 1024  # Size in MB
    logging.info("OK %s (%.2f MB)", local_path, size)

    return local_path
