"""Pure hourly aggregation and weather join logic."""

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

from src.weather import validate_processed_weather

TIME_METRIC_EXCLUSION_FLAGS = (
    "is_ambiguous_pickup_datetime",
    "is_nonexistent_pickup_datetime",
    "is_ambiguous_dropoff_datetime",
    "is_nonexistent_dropoff_datetime",
    "is_nonpositive_duration",
    "is_long_duration",
    "is_near_24h_duration",
    "is_over_24h_duration",
    "is_implausible_speed",
    "is_negative_distance",
    "is_extreme_distance",
)
REPORTED_TIME_QUALITY_FLAGS = (*TIME_METRIC_EXCLUSION_FLAGS, "is_zero_distance")

QUALITY_COUNT_NAMES = {
    "is_missing_dropoff": "missing_dropoff_count",
    **{flag: f"{flag.removeprefix('is_')}_count" for flag in REPORTED_TIME_QUALITY_FLAGS},
}
REQUIRED_TRIP_COLUMNS = {
    "pickup_datetime",
    "total_amount",
    "trip_duration_minutes",
    "trip_distance",
    "average_speed_mph",
    "is_missing_dropoff",
    "is_outside_reporting_month",
    "is_exact_duplicate",
    *REPORTED_TIME_QUALITY_FLAGS,
}


def _month_bounds(year: int, month: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    try:
        start = pd.Timestamp(year=year, month=month, day=1)
    except (TypeError, ValueError) as error:
        raise ValueError("year and month must identify a valid calendar month") from error
    return start, start + pd.DateOffset(months=1)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.where(denominator.ne(0)))


def _validate_trips(trips: pd.DataFrame, year: int, month: int) -> None:
    start, end = _month_bounds(year, month)
    if not isinstance(trips, pd.DataFrame) or trips.empty:
        raise ValueError(f"Taxi data for {year}-{month:02d} is empty")

    missing = REQUIRED_TRIP_COLUMNS - set(trips.columns)
    if missing:
        raise ValueError(f"Taxi data is missing required columns: {sorted(missing)}")

    pickup = trips["pickup_datetime"]
    if not is_datetime64_any_dtype(pickup.dtype) or isinstance(pickup.dtype, pd.DatetimeTZDtype):
        raise ValueError("pickup_datetime must contain naive local datetimes")
    if pickup.isna().any():
        raise ValueError("pickup_datetime contains null values")

    outside = ~pickup.between(start, end, inclusive="left")
    if outside.any():
        raise ValueError(
            f"Taxi partition contains {int(outside.sum())} row(s) "
            f"outside expected period {year}-{month:02d}"
        )

    for column in (
        "total_amount",
        "trip_duration_minutes",
        "trip_distance",
        "average_speed_mph",
    ):
        values = trips[column]
        if is_bool_dtype(values.dtype) or not is_numeric_dtype(values.dtype):
            raise ValueError(f"{column} must be numeric")
        if (~np.isfinite(values.dropna())).any():
            raise ValueError(f"{column} contains non-finite values")

    for column in {
        "is_missing_dropoff",
        "is_outside_reporting_month",
        "is_exact_duplicate",
        *REPORTED_TIME_QUALITY_FLAGS,
    }:
        if not is_bool_dtype(trips[column].dtype) or trips[column].isna().any():
            raise ValueError(f"{column} must be a non-null boolean column")


def aggregate_trips_hourly(trips: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    """Aggregate one physical event-month partition to pickup-hour grain."""
    _validate_trips(trips, year, month)

    frame = trips[
        [
            "pickup_datetime",
            "total_amount",
            "trip_duration_minutes",
            "trip_distance",
            "average_speed_mph",
        ]
    ].copy()
    frame["pickup_hour"] = frame["pickup_datetime"].dt.floor("h")

    missing_metric = (
        frame[["trip_duration_minutes", "trip_distance", "average_speed_mph"]].isna().any(axis=1)
    )
    time_flagged = (
        trips[["is_missing_dropoff", *TIME_METRIC_EXCLUSION_FLAGS]].any(axis=1) | missing_metric
    )
    valid = ~time_flagged

    hourly = frame.groupby("pickup_hour", sort=True).agg(
        trip_record_count=("pickup_datetime", "size"),
        total_amount_sum=("total_amount", "sum"),
        total_amount_count=("total_amount", "count"),
    )
    valid_hourly = (
        frame.loc[valid]
        .groupby("pickup_hour", sort=True)
        .agg(
            valid_time_count=("pickup_datetime", "size"),
            duration_minutes_sum=("trip_duration_minutes", "sum"),
            duration_minutes_count=("trip_duration_minutes", "count"),
            distance_miles_sum=("trip_distance", "sum"),
            distance_miles_count=("trip_distance", "count"),
            speed_mph_sum=("average_speed_mph", "sum"),
            speed_mph_count=("average_speed_mph", "count"),
        )
    )
    hourly = hourly.join(valid_hourly, how="left")

    hourly["time_flagged_count"] = time_flagged.groupby(frame["pickup_hour"]).sum()
    hourly["missing_metric_value_count"] = missing_metric.groupby(frame["pickup_hour"]).sum()
    hourly["source_period_mismatch_count"] = (
        trips["is_outside_reporting_month"].groupby(frame["pickup_hour"]).sum()
    )
    hourly["exact_duplicate_count"] = (
        trips["is_exact_duplicate"].groupby(frame["pickup_hour"]).sum()
    )
    for flag, output_name in QUALITY_COUNT_NAMES.items():
        hourly[output_name] = trips[flag].groupby(frame["pickup_hour"]).sum()

    count_columns = [
        column
        for column in hourly.columns
        if column.endswith("_count") or column == "trip_record_count"
    ]
    sum_columns = [column for column in hourly.columns if column.endswith("_sum")]
    hourly[count_columns] = hourly[count_columns].fillna(0).astype("int64")
    hourly[sum_columns] = hourly[sum_columns].fillna(0.0).astype("float64")

    if not (hourly["valid_time_count"] + hourly["time_flagged_count"]).equals(
        hourly["trip_record_count"]
    ):
        raise RuntimeError("Analytics row-count reconciliation failed")

    hourly["avg_total_amount"] = _safe_ratio(
        hourly["total_amount_sum"], hourly["total_amount_count"]
    )
    hourly["avg_duration_min"] = _safe_ratio(
        hourly["duration_minutes_sum"], hourly["duration_minutes_count"]
    )
    hourly["avg_distance_mi"] = _safe_ratio(
        hourly["distance_miles_sum"], hourly["distance_miles_count"]
    )
    hourly["avg_speed_mph"] = _safe_ratio(hourly["speed_mph_sum"], hourly["speed_mph_count"])
    hourly["aggregate_speed_mph"] = _safe_ratio(
        hourly["distance_miles_sum"] * 60.0,
        hourly["duration_minutes_sum"],
    )
    hourly["pct_time_flagged"] = (
        _safe_ratio(hourly["time_flagged_count"], hourly["trip_record_count"]) * 100
    )
    return hourly.reset_index()


def join_hourly_weather(
    hourly_trips: pd.DataFrame,
    weather: pd.DataFrame,
    year: int,
    month: int,
) -> pd.DataFrame:
    """Join two validated one-row-per-hour datasets without silent misses."""
    if hourly_trips.empty or "pickup_hour" not in hourly_trips:
        raise ValueError("Hourly taxi data is empty or missing pickup_hour")
    if hourly_trips["pickup_hour"].duplicated().any():
        raise ValueError("Hourly taxi data contains duplicate pickup_hour values")
    validate_processed_weather(weather, year, month)

    result = hourly_trips.merge(
        weather,
        left_on="pickup_hour",
        right_on="observed_hour",
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    unmatched = result["_merge"].ne("both")
    if unmatched.any():
        raise ValueError(f"Weather join left {int(unmatched.sum())} unmatched taxi hours")
    return result.drop(columns=["observed_hour", "_merge"])


def build_trips_weather_hourly(
    trips: pd.DataFrame,
    weather: pd.DataFrame,
    year: int,
    month: int,
) -> pd.DataFrame:
    return join_hourly_weather(aggregate_trips_hourly(trips, year, month), weather, year, month)
