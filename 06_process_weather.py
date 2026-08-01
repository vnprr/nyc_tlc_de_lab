"""Process raw weather JSON into typed, partitioned parquet.

No manifest here on purpose: derived zone with deterministic keys and
cheap full recompute (a few small files), so overwrite-all is simpler
and equally idempotent.
"""

import json
import logging
import re
from pathlib import Path

from src.config import (
    BUCKET,
    PROCESSED_WEATHER_PREFIX,
    RAW_WEATHER_PREFIX,
    WORKDIR,
)
from src.logging_setup import setup_logging
from src.s3_io import list_keys, s3, upload_df_overwrite
from src.weather import process_weather_payload

FILE_PATTERN = re.compile(r"weather_(?P<year>\d{4})-(?P<month>\d{2})\.json")

if __name__ == "__main__":
    setup_logging(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    for key in list_keys(BUCKET, RAW_WEATHER_PREFIX, suffix=".json"):
        match = FILE_PATTERN.fullmatch(Path(key).name)
        if match is None:
            raise ValueError(f"Unexpected raw weather file: {key}")
        year, month = int(match["year"]), int(match["month"])

        payload = json.loads(
            s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        )
        df = process_weather_payload(payload, year, month)

        out_key = (f"{PROCESSED_WEATHER_PREFIX}year={year}/month={month:02d}/"
                   f"weather_{year}-{month:02d}.parquet")
        upload_df_overwrite(df, BUCKET, out_key, WORKDIR)