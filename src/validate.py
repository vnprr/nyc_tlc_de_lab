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

# V5
SCHEMA_V1 = REQUIRED_COLUMNS
SCHEMA_V2 = SCHEMA_V1 | {"cbd_congestion_fee"} # unia zbiorów
KNOWN_SCHEMAS = {
    "v1_through_2024" : SCHEMA_V1,
    "v2_from_2025_01" : SCHEMA_V2
}


def validate_source(df: pd.DataFrame) -> None:
    errors = []

    if df.empty:
        errors.append("Dataset is empty.")

    if set(df.columns) == SCHEMA_V1:
        logging.info("Found matching schema: `v1_through_2024`")
    elif set(df.columns) == SCHEMA_V2:
        logging.info("Found matching schema: `v2_from_2025_01`")
    else:
        logging.error("Unknown schema!")
        errors.append("Unknown schema!")
    
    # missing_columns = (SCHEMA_V1 | SCHEMA_V2) - set(df.columns)
    # # missing_columns = REQUIRED_COLUMNS - set(df.columns)
    # # unexpected_columns = set(df.columns) - REQUIRED_COLUMNS

    # if missing_columns:
    #     errors.append(
    #         f"Missing required columns: {sorted(missing_columns)}"
    #     )

    # if unexpected_columns:
    #     errors.append(
    #         "Unexpected columns for the current source schema: "
    #         f"{sorted(unexpected_columns)}"
    #     )

    # tu było if not missing_columns:
    if not errors:
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
