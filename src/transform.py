import logging

import numpy as np
import pandas as pd


QUALITY_FLAGS = [
    "is_flex_fare_record",
    "is_unknown_ratecode",
    "is_negative_transaction",
    "has_amount_sign_mismatch",
    "is_outside_reporting_month",
    "has_nonpositive_duration",
    "has_suspicious_long_duration",
    "has_near_24h_duration",
    "has_extreme_duration",
    "has_negative_distance",
    "has_zero_distance",
    "has_extreme_distance",
    "has_implausible_speed",
    "has_zero_passengers",
]


def transform_trips(
    df: pd.DataFrame,
    reporting_year: int,
    reporting_month: int,
    source_file: str,
    processing_time: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split source rows into processed and rejected datasets."""
    if not 1 <= reporting_month <= 12:
        raise ValueError("reporting_month must be between 1 and 12")

    reporting_start = pd.Timestamp(
        year=reporting_year,
        month=reporting_month,
        day=1,
    )
    reporting_end = reporting_start + pd.DateOffset(months=1)
    trusted_start = reporting_start - pd.DateOffset(years=1)

    if processing_time is None:
        processing_time = pd.Timestamp.now()
    else:
        processing_time = pd.Timestamp(processing_time)

    if processing_time.tz is not None:
        processing_time = processing_time.tz_localize(None)

    source = df.copy()
    source["source_file"] = source_file

    pickup = source["tpep_pickup_datetime"]

    rejected_mask = (
        pickup.isna()
        | pickup.lt(trusted_start)
        | pickup.gt(processing_time)
    )

    rejected = source.loc[rejected_mask].copy()
    rejected["rejection_reason"] = (
        "untrustworthy_pickup_timestamp"
    )

    result = source.loc[~rejected_mask].copy()

    pickup = result["tpep_pickup_datetime"]
    dropoff = result["tpep_dropoff_datetime"]

    # Documented TLC categories.
    result["is_flex_fare_record"] = (
        result["payment_type"] == 0
    )
    result["is_unknown_ratecode"] = (
        result["RatecodeID"] == 99
    )

    # Monetary flags.
    negative_fare = result["fare_amount"] < 0
    negative_total = result["total_amount"] < 0

    result["is_negative_transaction"] = negative_total
    result["has_amount_sign_mismatch"] = (
        negative_fare != negative_total
    )

    # Reporting period.
    result["is_outside_reporting_month"] = ~pickup.between(
        reporting_start,
        reporting_end,
        inclusive="left",
    )

    # Duration.
    result["trip_duration_minutes"] = (
        dropoff - pickup
    ).dt.total_seconds().div(60)

    duration = result["trip_duration_minutes"]

    result["has_nonpositive_duration"] = duration.le(0)
    result["has_suspicious_long_duration"] = (
        duration.gt(360)
        & duration.lt(1380)
    )
    result["has_near_24h_duration"] = (
        duration.ge(1380)
        & duration.lt(1440)
    )
    result["has_extreme_duration"] = duration.ge(1440)

    # Distance.
    distance = result["trip_distance"]

    result["has_negative_distance"] = distance.lt(0)
    result["has_zero_distance"] = distance.eq(0)
    result["has_extreme_distance"] = distance.gt(100)

    # Average speed is calculated only for usable inputs.
    valid_speed_input = duration.gt(0) & distance.ge(0)

    result["average_speed_mph"] = np.nan
    result.loc[
        valid_speed_input,
        "average_speed_mph",
    ] = (
        distance.loc[valid_speed_input]
        / (duration.loc[valid_speed_input] / 60)
    )

    result["has_implausible_speed"] = (
        result["average_speed_mph"] > 80
    )

    # Passenger count.
    result["has_zero_passengers"] = (
        result["passenger_count"] == 0
    )

    logging.info(
        "Trip transformation completed: %s processed, %s rejected",
        f"{len(result):,}",
        f"{len(rejected):,}",
    )

    return result, rejected


def create_quality_summary(
    processed_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
    raw_row_count: int,
) -> pd.DataFrame:
    """Create quality metrics and enforce row-count reconciliation."""
    output_row_count = len(processed_df) + len(rejected_df)

    if raw_row_count != output_row_count:
        raise ValueError(
            "Row count reconciliation failed: "
            f"raw={raw_row_count:,}, "
            f"processed={len(processed_df):,}, "
            f"rejected={len(rejected_df):,}"
        )

    missing_flags = set(QUALITY_FLAGS) - set(processed_df.columns)

    if missing_flags:
        raise ValueError(
            f"Missing quality flags: {sorted(missing_flags)}"
        )

    metrics = {
        "raw_rows": raw_row_count,
        "processed_rows": len(processed_df),
        "rejected_rows": len(rejected_df),
    }
    metrics.update(
        processed_df[QUALITY_FLAGS]
        .sum()
        .astype("int64")
        .to_dict()
    )

    summary = pd.Series(metrics, name="count").to_frame()
    summary.index.name = "metric"
    summary["percentage_of_raw"] = (
        summary["count"]
        .div(raw_row_count)
        .mul(100)
        .round(4)
    )

    return summary
