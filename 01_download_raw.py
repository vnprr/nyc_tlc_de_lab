from pathlib import Path
import requests

# Data catalog
RAW_DIR = Path("data/raw_download")
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Config constants
BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
DATASET = "yellow_tripdata"
MONTHS = ["2024-01", "2024-02", "2024-03"]

def download_month(month: str) -> Path:
    """
    Download the dataset for a specific month and save it to the raw data directory.

    Args:
        month (str): The month in 'YYYY-MM'
    """
    filename = f"{DATASET}_{month}.parquet"
    url = f"{BASE_URL}/{filename}"
    local_path = RAW_DIR / filename

    if local_path.exists():
        print(f"SKIP   {filename} (already downloaded)")
        return local_path

    print(f"GET: {url}")

    response = requests.get(url=url, timeout=60, stream=True)

    response.raise_for_status()                                         # Raise an error for bad responses

    temp_file = local_path.with_suffix(".tmp")                          # Create a temporary file to avoid partial downloads

    with open(temp_file, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):     # 1 MB chunks
            f.write(chunk)
    
    temp_file.rename(local_path)

    size = local_path.stat().st_size /1024 / 1024  # Size in MB
    print(f"OK: {local_path} ({size:.2f} MB).")

    return local_path

if __name__ == "__main__":
    for month in MONTHS:
        download_month(month)