"""Physical contract for monthly NYC TLC source files."""

import logging
from numbers import Integral

import numpy as np
import pandas as pd
from pandas.api.types import (
    infer_dtype,
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
)

SCHEMA_V1 = frozenset(
    {
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
)
SCHEMA_V2 = SCHEMA_V1 | {"cbd_congestion_fee"}
SCHEMA_V2_START = (2025, 1)

DATETIME_COLUMNS = {"tpep_pickup_datetime", "tpep_dropoff_datetime"}
STRING_COLUMNS = {"store_and_fwd_flag"}
ALLOWED_VALUES = {
    "VendorID": {1, 2, 6, 7},
    "RatecodeID": {1, 2, 3, 4, 5, 6, 99},
    "payment_type": {0, 1, 2, 3, 4, 5, 6},
    "store_and_fwd_flag": {"Y", "N"},
}


def _expected_schema(year: int, month: int) -> tuple[str, frozenset[str]]:
    if (
        isinstance(year, bool)
        or not isinstance(year, Integral)
        or not 1 <= year <= 9999
        or isinstance(month, bool)
        or not isinstance(month, Integral)
        or not 1 <= month <= 12
    ):
        raise ValueError("year and month must identify a valid calendar month")
    if (year, month) < SCHEMA_V2_START:
        return "v1_through_2024", SCHEMA_V1
    return "v2_from_2025_01", SCHEMA_V2


def _domain_warnings(df: pd.DataFrame) -> None:
    """Report unexpected row values without rejecting a structurally valid file."""
    for column, allowed in ALLOWED_VALUES.items():
        invalid = df[column].notna() & ~df[column].isin(allowed)
        if invalid.any():
            sample = [repr(value) for value in df.loc[invalid, column].unique()[:10]]
            logging.warning(
                "%s contains %d value(s) outside the documented domain; sample=%s",
                column,
                int(invalid.sum()),
                sample,
            )


def validate_source(df: pd.DataFrame, reporting_year: int, reporting_month: int) -> None:
    """Fail on broken schema or physical types for the source month.

    Domain anomalies are warnings.  They describe individual records and do
    not prove that the complete file is unusable.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")

    schema_name, expected = _expected_schema(reporting_year, reporting_month)
    errors: list[str] = []
    if df.empty:
        errors.append("Dataset is empty")

    duplicates = df.columns[df.columns.duplicated()].tolist()
    if duplicates:
        errors.append(f"Duplicate columns are not allowed: {duplicates}")

    actual = set(df.columns)
    if actual != expected:
        errors.append(
            f"Schema does not match {schema_name}: "
            f"missing columns={sorted(expected - actual)}; "
            f"unexpected columns={sorted(actual - expected)}"
        )

    if not duplicates and actual == expected:
        for column in DATETIME_COLUMNS:
            dtype = df[column].dtype
            if not is_datetime64_any_dtype(dtype):
                errors.append(f"{column} must be a datetime column; found {dtype}")
            elif getattr(dtype, "tz", None) is not None:
                errors.append(f"{column} must contain timezone-naive local time")

        numeric_columns = expected - DATETIME_COLUMNS - STRING_COLUMNS
        for column in sorted(numeric_columns):
            values = df[column]
            if is_bool_dtype(values.dtype) or not is_numeric_dtype(values.dtype):
                errors.append(f"{column} must be numeric; found {values.dtype}")
            elif (~np.isfinite(values.dropna())).any():
                errors.append(f"{column} must contain only finite numeric values")

        for column in STRING_COLUMNS:
            inferred = infer_dtype(df[column].dropna(), skipna=True)
            if inferred not in {"empty", "string"}:
                errors.append(f"{column} must contain only strings or nulls")

    if errors:
        raise ValueError("Source validation failed:\n- " + "\n- ".join(errors))

    logging.info("Found matching schema: %s", schema_name)
    _domain_warnings(df)
    logging.info("Source validation passed")
