import logging
from pathlib import Path
import pandas as pd

from functions.validate_data_source import validate_source

PROJECT_DIR = Path(__file__).resolve().parent
DATA_FILE = PROJECT_DIR / "data/raw_download/yellow_tripdata_2024-01.parquet"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def load_source(file_path: Path) -> pd.DataFrame:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_size = file_path.stat().st_size
        
    if file_size == 0:
        raise ValueError(f"File is empty: {file_path}")
    
    file_size_mb = file_size / (1024 * 1024)

    logging.info("Source file found: %s", file_path)
    logging.info("File size: %.2f MB", file_size_mb)
    
    df = pd.read_parquet(file_path)

    logging.info("Loading source data from: %s", file_path)

    return df

def log_basic_info(df: pd.DataFrame):

    logging.info("DataFrame loaded")
    logging.info("Rows: %s", len(df))
    logging.info("Columns: %s", len(df.columns))
    logging.info("Column names: %s", list(df.columns))
    
    missing = df.isna().sum()
    if missing.any():
        logging.info("Missing values:\n%s", missing[missing > 0].sort_values(ascending=False))
    else:
        logging.info("No missing values found.")


if __name__ == "__main__":
    df = load_source(DATA_FILE)
    log_basic_info(df)
    validate_source(df)
