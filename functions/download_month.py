
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
