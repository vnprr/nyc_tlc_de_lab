import logging

import numpy as np
import pandas as pd


QUALITY_FLAGS = [
    "is_flex_fare_record",
    "is_unknown_ratecode",
    "is_negative_transaction",
    "has_amount_sign_mismatch",
    "is_outside_reporting_month",
    "has_untrustworthy_timestamp",
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
) -> pd.DataFrame:
    if not 1 <= reporting_month <= 12:
        raise ValueError("reporting_month must be between 1 and 12")

    # Do not modify the source DataFrame.
    result = df.copy()

    reporting_start = pd.Timestamp(
        year=reporting_year,
        month=reporting_month,
        day=1,
    )
    reporting_end = reporting_start + pd.DateOffset(months=1)

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

    # Clearly untrustworthy historical or future timestamps.
    trusted_start = reporting_start - pd.DateOffset(years=1)
    trusted_end = reporting_end + pd.DateOffset(years=1)

    result["has_untrustworthy_timestamp"] = (
        pickup.lt(trusted_start)
        | pickup.ge(trusted_end)
        | dropoff.lt(trusted_start)
        | dropoff.ge(trusted_end)
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
        "Trip transformation completed: %s rows",
        f"{len(result):,}",
    )

    return result


def create_quality_summary(
    df: pd.DataFrame,
) -> pd.DataFrame:
    counts = df[QUALITY_FLAGS].sum().astype("int64")

    return pd.DataFrame({
        "count": counts,
        "percentage": (
            counts.div(len(df)).mul(100).round(4)
        ),
    })