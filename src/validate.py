import logging

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

REQUIRED_COLUMNS = {
    "VendorID",
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "passenger_count",
    "trip_distance",
    "RatecodeID",
    "store_and_fwd_flag",
    "PULocationID",
    "DOLocationID",
    "payment_type",
    "fare_amount",
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "total_amount",
    "congestion_surcharge",
    "Airport_fee",
}


ALLOWED_VALUES = {
    "VendorID": {1, 2, 6, 7},
    "RatecodeID": {1, 2, 3, 4, 5, 6, 99},
    "payment_type": {0, 1, 2, 3, 4, 5, 6},
    "store_and_fwd_flag": {"Y", "N"},
}


def validate_source(df: pd.DataFrame) -> None:
    logging.info("Source validation passed")
    
    errors = []

    if df.empty:
        errors.append("Dataset is empty.")

    missing_columns = REQUIRED_COLUMNS - set(df.columns)

    if missing_columns:
        errors.append(
            f"Missing required columns: {sorted(missing_columns)}"
        )

    if not missing_columns:
        datetime_columns = [
            "tpep_pickup_datetime",
            "tpep_dropoff_datetime",
        ]

        for column in datetime_columns:
            if not is_datetime64_any_dtype(df[column]):
                errors.append(
                    f"{column} is not a datetime column."
                )

        for column, allowed_values in ALLOWED_VALUES.items():
            observed_values = set(df[column].dropna().unique())
            invalid_values = observed_values - allowed_values

            if invalid_values:
                errors.append(
                    f"{column} contains invalid values: "
                    f"{sorted(invalid_values)}"
                )

    if errors:
        message = "\n- ".join(errors)

        raise ValueError(
            f"Source validation failed:\n- {message}"
        )

    logging.info("Source validation passed")